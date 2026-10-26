import asyncio
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

import blocage as blocage_mod
import credit as credit_mod
import liens as liens_mod
import notifications as notif_mod
import pdfgen
import stockage_pdf
from doc import Document, dele, ins

log = logging.getLogger("editeur")
app = FastAPI(title="Editeur de documents partage")

DOSSIER = os.path.dirname(os.path.abspath(__file__))

# Un seul processus : cet etat est donc unique. (A remplacer par DynamoDB.)
DOCUMENTS = {}
CREDIT = credit_mod.creer()
BLOCAGE = blocage_mod.creer()
LIENS = liens_mod.creer()
STOCK = stockage_pdf.creer()
NOTIF = notif_mod.creer()
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

EPUISES = set()      # liens dont on sait qu'ils sont epuises : reponse sans toucher a la base
TICKETS = {}         # ticket -> {"cle": cle du PDF, "doc_id": document}
EN_COURS = {}        # fabrications de PDF en cours : cle -> travail
VERROU_PDF = threading.Lock()
POOL = ThreadPoolExecutor(max_workers=2)    # les "travailleurs" qui fabriquent les PDF

SALLES = {}          # doc_id -> ensemble des connexions temps reel ouvertes sur ce document


# ---------------------------------------------------------------- modeles

class NouveauDocument(BaseModel):
    titre: str = Field(min_length=1, max_length=200)


class NouveauMembre(BaseModel):
    email: str = Field(min_length=3, max_length=200)


class NouveauLien(BaseModel):
    max_telechargements: int = Field(ge=1, le=100_000)


class OperationIn(BaseModel):
    kind: Literal["ins", "del"]
    pos: int = Field(ge=0)
    text: str = Field(default="", max_length=10_000)
    length: int = Field(default=0, ge=0, le=10_000)


class Soumission(BaseModel):
    base: int = Field(ge=0)      # version que voyait le redacteur
    op: OperationIn


# ---------------------------------------------------------------- aides

def _email(x_email):
    if not x_email or "@" not in x_email:
        raise HTTPException(401, "En-tete X-Email manquant ou invalide")
    return x_email.strip().lower()


def _document(doc_id, email):
    entree = DOCUMENTS.get(doc_id)
    if entree is None:
        raise HTTPException(404, "Document inconnu")
    if email not in entree["membres"]:
        raise HTTPException(403, "Acces refuse a ce document")
    return entree


def _admin(x_admin_token):
    if not ADMIN_TOKEN or x_admin_token != ADMIN_TOKEN:
        raise HTTPException(403, "Jeton d'administration invalide")


# ---------------------------------------------------------------- pages

@app.get("/", include_in_schema=False)
def page_accueil():
    return FileResponse(os.path.join(DOSSIER, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(DOSSIER, "static")), name="static")


# ---------------------------------------------------------------- credit

@app.get("/credit")
def mon_credit(x_email: str = Header(default="")):
    email = _email(x_email)
    jour = credit_mod.jour_utc()
    utilises = CREDIT.utilises(email, jour)
    return {
        "jour": jour,
        "limite": CREDIT.limite,
        "utilises": utilises,
        "restant": CREDIT.limite - utilises,
    }


# ---------------------------------------------------------------- documents

@app.get("/documents")
def lister_documents(x_email: str = Header(default="")):
    email = _email(x_email)
    return {"documents": [
        {"id": doc_id, "titre": e["titre"], "createur": e["createur"]}
        for doc_id, e in DOCUMENTS.items() if email in e["membres"]
    ]}


@app.post("/documents", status_code=201)
def creer_document(corps: NouveauDocument, x_email: str = Header(default="")):
    email = _email(x_email)
    doc_id = uuid.uuid4().hex[:10]
    DOCUMENTS[doc_id] = {
        "doc": Document(),
        "titre": corps.titre,
        "createur": email,
        "membres": {email},
        "derniere_activite": time.time(),
    }
    return {"id": doc_id, "version": 0}


@app.post("/documents/{doc_id}/membres", status_code=201)
def ajouter_membre(doc_id: str, corps: NouveauMembre, x_email: str = Header(default="")):
    email = _email(x_email)
    entree = _document(doc_id, email)
    if email != entree["createur"]:
        raise HTTPException(403, "Seul le createur peut donner acces")
    entree["membres"].add(corps.email.strip().lower())
    return {"membres": sorted(entree["membres"])}


@app.get("/documents/{doc_id}")
def lire_document(doc_id: str, x_email: str = Header(default="")):
    entree = _document(doc_id, _email(x_email))
    texte, version = entree["doc"].instantane()
    return {"id": doc_id, "titre": entree["titre"], "texte": texte, "version": version}


def _traiter_op(entree, email, corps):
    """Le coeur de l'ecriture : blocage, credit, ordre des modifications.
    Renvoie {version, ops, credit_restant} ou leve une HTTPException."""
    reste = BLOCAGE.reste(email)
    if reste > 0:
        raise HTTPException(
            429,
            detail={"erreur": "bloque", "reessayer_dans_s": int(reste) + 1},
            headers={"Retry-After": str(int(reste) + 1)},
        )

    o = corps.op
    if o.kind == "ins":
        if o.text == "":
            raise HTTPException(422, "ins : text ne peut pas etre vide")
        if any(ord(ch) > 0xFFFF for ch in o.text):
            # JavaScript compte ces caracteres (emoji...) en double : positions decalees
            raise HTTPException(422, "ins : caracteres hors plan multilingue de base non pris en charge")
        op = ins(o.pos, o.text)
        cout = len(o.text)          # inserer coute 1 par caractere
    else:
        if o.length < 1:
            raise HTTPException(422, "del : length doit etre >= 1")
        op = dele(o.pos, o.length)
        cout = 0                    # supprimer est gratuit

    # On fixe le jour une seule fois, pour que le remboursement vise la
    # meme page que le paiement (meme si minuit passe entre les deux).
    jour = credit_mod.jour_utc()

    if cout > 0:
        utilises = CREDIT.consommer(email, cout, jour)   # verifier ET retirer
        if utilises is None:
            if BLOCAGE.enregistrer_refus(email):
                reste = BLOCAGE.reste(email)
                raise HTTPException(
                    429,
                    detail={"erreur": "bloque", "reessayer_dans_s": int(reste) + 1},
                    headers={"Retry-After": str(int(reste) + 1)},
                )
            restant = CREDIT.limite - CREDIT.utilises(email, jour)
            raise HTTPException(
                429,
                detail={"erreur": "credit_epuise", "demande": cout, "restant": restant},
            )

    try:
        acceptees, version = entree["doc"].soumettre(op, corps.base)
    except ValueError as e:
        if cout > 0:
            CREDIT.rembourser(email, cout, jour)         # erreur : on rend les caracteres
        raise HTTPException(422, str(e))

    entree["derniere_activite"] = time.time()
    restant = CREDIT.limite - CREDIT.utilises(email, jour)
    # "ops" peut etre vide : tout ce que tu supprimais l'etait deja
    return {"version": version, "ops": [asdict(a) for a in acceptees], "credit_restant": restant}


@app.post("/documents/{doc_id}/ops")
async def soumettre(doc_id: str, corps: Soumission, x_email: str = Header(default="")):
    # "async" voulu : tout se passe dans le meme fil que les connexions temps reel,
    # donc l'ordre des messages envoyes est toujours celui du journal.
    email = _email(x_email)
    entree = _document(doc_id, email)
    res = _traiter_op(entree, email, corps)
    _publier(doc_id, email, res, auteur=None)
    return res


@app.get("/documents/{doc_id}/ops")
def lire_ops(doc_id: str, depuis: int = 0, x_email: str = Header(default="")):
    entree = _document(doc_id, _email(x_email))
    depuis = max(0, depuis)
    ops, version = entree["doc"].journal_depuis(depuis)
    return {"depuis": depuis, "version": version, "ops": [asdict(o) for o in ops]}


class Restauration(BaseModel):
    version: int = Field(ge=0)


@app.get("/documents/{doc_id}/versions")
def lister_versions(doc_id: str, x_email: str = Header(default="")):
    entree = _document(doc_id, _email(x_email))
    _, courante = entree["doc"].instantane()
    # chaque modification accepte cree une version : 0 (vide) jusqu'a "courante"
    return {"courante": courante, "consultables": f"0 a {courante}",
            "recentes": list(range(max(0, courante - 49), courante + 1))}


@app.get("/documents/{doc_id}/versions/{numero}")
def lire_version(doc_id: str, numero: int, x_email: str = Header(default="")):
    entree = _document(doc_id, _email(x_email))
    try:
        texte = entree["doc"].texte_a(numero)
    except ValueError:
        raise HTTPException(404, "Version inconnue")
    return {"version": numero, "texte": texte}


@app.post("/documents/{doc_id}/restaurer")
async def restaurer_version(doc_id: str, corps: Restauration, x_email: str = Header(default="")):
    email = _email(x_email)
    entree = _document(doc_id, email)
    reste = BLOCAGE.reste(email)
    if reste > 0:
        raise HTTPException(429, detail={"erreur": "bloque", "reessayer_dans_s": int(reste) + 1},
                            headers={"Retry-After": str(int(reste) + 1)})
    try:
        ancien = entree["doc"].texte_a(corps.version)
    except ValueError:
        raise HTTPException(404, "Version inconnue")
    jour = credit_mod.jour_utc()
    cout = len(ancien)                  # restaurer = reecrire le texte : meme prix qu'une insertion
    if cout > 0 and CREDIT.consommer(email, cout, jour) is None:
        restant = CREDIT.limite - CREDIT.utilises(email, jour)
        raise HTTPException(429, detail={"erreur": "credit_epuise", "demande": cout, "restant": restant})
    try:
        acceptees, version, _ = entree["doc"].restaurer(corps.version)
    except ValueError as e:
        if cout > 0:
            CREDIT.rembourser(email, cout, jour)
        raise HTTPException(422, str(e))
    entree["derniere_activite"] = time.time()
    res = {"version": version, "ops": [asdict(a) for a in acceptees],
           "credit_restant": CREDIT.limite - CREDIT.utilises(email, jour), "restaure": corps.version}
    _publier(doc_id, email, res, auteur=None)
    return res


# ---------------------------------------------------------------- temps reel (WebSocket)

class Connexion:
    def __init__(self, ws, email, nom):
        self.ws = ws
        self.email = email
        self.nom = nom
        self.id = uuid.uuid4().hex[:6]
        self.curseur = 0
        self.file = asyncio.Queue()      # messages a envoyer, dans l'ordre


def _decaler_curseur(c, op):
    if op["kind"] == "ins":
        return c + len(op["text"]) if op["pos"] <= c else c
    p, n = op["pos"], op["length"]
    if c <= p:
        return c
    return c - n if c >= p + n else p


def _publier(doc_id, email, res, auteur):
    """Envoie le resultat d'une modification acceptee : un accuse a l'auteur
    (la connexion qui l'a envoyee), les operations aux autres connexions."""
    salle = SALLES.get(doc_id, ())
    for c in salle:
        for o in res["ops"]:
            c.curseur = _decaler_curseur(c.curseur, o)
        if c is auteur:
            c.file.put_nowait({"type": "ack", "version": res["version"], "ops": res["ops"],
                               "credit_restant": res["credit_restant"]})
        elif res["ops"]:
            c.file.put_nowait({"type": "ops", "version": res["version"], "auteur": email,
                               "ops": res["ops"]})


def _diffuser_presence(doc_id):
    salle = SALLES.get(doc_id, ())
    msg = {"type": "presence", "utilisateurs": [
        {"id": c.id, "email": c.email, "nom": c.nom, "curseur": c.curseur} for c in salle]}
    for c in salle:
        c.file.put_nowait(msg)


async def _envoyeur(conn):
    try:
        while True:
            await conn.ws.send_json(await conn.file.get())
    except Exception:
        return


@app.websocket("/documents/{doc_id}/live")
async def temps_reel(ws: WebSocket, doc_id: str, email: str = "", nom: str = ""):
    email = email.strip().lower()
    entree = DOCUMENTS.get(doc_id)
    if "@" not in email or entree is None or email not in entree["membres"]:
        await ws.close(code=4403)
        return
    await ws.accept()

    conn = Connexion(ws, email, (nom or email)[:60])
    SALLES.setdefault(doc_id, set()).add(conn)
    texte, version = entree["doc"].instantane()
    conn.file.put_nowait({"type": "etat", "texte": texte, "version": version})
    _diffuser_presence(doc_id)
    envoi = asyncio.create_task(_envoyeur(conn))
    try:
        while True:
            try:
                data = await ws.receive_json()
            except ValueError:
                conn.file.put_nowait({"type": "erreur", "code": 400, "detail": "JSON invalide"})
                continue
            if not isinstance(data, dict):
                continue
            genre = data.get("type")
            if genre == "op":
                try:
                    corps = Soumission.model_validate({"base": data.get("base"), "op": data.get("op")})
                    res = _traiter_op(entree, email, corps)
                except ValidationError:
                    conn.file.put_nowait({"type": "erreur", "code": 422, "detail": "requete invalide"})
                except HTTPException as e:
                    conn.file.put_nowait({"type": "erreur", "code": e.status_code, "detail": e.detail})
                else:
                    _publier(doc_id, email, res, auteur=conn)
            elif genre == "curseur":
                try:
                    texte, _ = entree["doc"].instantane()
                    conn.curseur = max(0, min(int(data.get("pos", 0)), len(texte)))
                except (TypeError, ValueError):
                    continue
                _diffuser_presence(doc_id)
            elif genre == "sync":
                texte, version = entree["doc"].instantane()
                conn.file.put_nowait({"type": "etat", "texte": texte, "version": version})
    except WebSocketDisconnect:
        pass
    finally:
        SALLES.get(doc_id, set()).discard(conn)
        envoi.cancel()
        _diffuser_presence(doc_id)


# ---------------------------------------------------------------- liens de telechargement

def _cle_pdf(doc_id, version):
    return f"pdf/{doc_id}/v{version}.pdf"


def _fabriquer(cle, titre, texte):
    try:
        STOCK.ecrire(cle, pdfgen.fabriquer_pdf(titre, texte))
    except Exception:
        log.exception("Echec de fabrication du PDF %s", cle)
    finally:
        with VERROU_PDF:
            EN_COURS.pop(cle, None)


def _lancer_fabrication(cle, titre, texte):
    """Une seule fabrication par PDF, meme si 100 visiteurs le demandent ensemble."""
    with VERROU_PDF:
        if cle in EN_COURS:
            return
        EN_COURS[cle] = POOL.submit(_fabriquer, cle, titre, texte)


def _servir(cle, doc_id):
    nom = f"document-{doc_id}.pdf"
    mode, valeur = STOCK.acces(cle, nom)
    if mode == "url":                       # S3 : le visiteur telecharge directement chez S3
        return RedirectResponse(valeur, status_code=302)
    return Response(
        content=valeur,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )


def _veut_html(request):
    return "text/html" in request.headers.get("accept", "")


def _page(titre, message, statut, rafraichir=None):
    refresh = f'<meta http-equiv="refresh" content="1;url={rafraichir}">' if rafraichir else ""
    return HTMLResponse(
        f'<!doctype html><html lang="fr"><head><meta charset="utf-8">{refresh}'
        f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{titre}</title></head>'
        f'<body style="font:18px system-ui;max-width:34rem;margin:4rem auto;padding:0 1rem">'
        f'<h1>{titre}</h1><p>{message}</p></body></html>', status_code=statut)


def _patiente(ticket, request=None):
    if request is not None and _veut_html(request):
        return _page("Votre exemplaire est r\u00e9serv\u00e9",
                     "Le PDF est en cours de pr\u00e9paration. Cette page se met \u00e0 jour toute seule : "
                     "ne la rechargez pas, cela consommerait un autre exemplaire.",
                     202, rafraichir=f"/telechargements/{ticket}")
    return JSONResponse(
        status_code=202,
        content={"etat": "patiente", "ticket": ticket, "reessayer_dans_s": 1},
        headers={"Retry-After": "1", "Location": f"/telechargements/{ticket}"},
    )


def _epuise(request=None):
    if request is not None and _veut_html(request):
        return _page("Lien \u00e9puis\u00e9", "Ce lien a atteint son nombre maximal de t\u00e9l\u00e9chargements.", 410)
    return JSONResponse(
        status_code=410,
        content={"etat": "epuise", "message": "Ce lien a atteint son nombre maximal de telechargements."},
    )


@app.post("/documents/{doc_id}/liens", status_code=201)
def creer_lien(doc_id: str, corps: NouveauLien, x_email: str = Header(default="")):
    email = _email(x_email)
    _document(doc_id, email)                 # il faut avoir acces au document
    lien_id = uuid.uuid4().hex[:12]
    LIENS.creer(lien_id, doc_id, email, corps.max_telechargements)
    return {
        "id": lien_id,
        "url": f"/liens/{lien_id}",
        "restants": corps.max_telechargements,
    }


@app.get("/liens/{lien_id}")
def utiliser_lien(lien_id: str, request: Request):
    # 1. On sait deja que c'est epuise : reponse immediate, sans toucher a la base
    if lien_id in EPUISES:
        return _epuise(request)

    info = LIENS.lire(lien_id)
    if info is None:
        raise HTTPException(404, "Lien inconnu")
    entree = DOCUMENTS.get(info["doc_id"])
    if entree is None:
        raise HTTPException(404, "Document du lien introuvable")

    # 2. Verifier ET retirer un exemplaire, en un seul geste
    restants = LIENS.prendre(lien_id)
    if restants is None:
        EPUISES.add(lien_id)
        return _epuise(request)

    # 3. Un seul visiteur recoit "0" : c'est lui qui declenche l'e-mail
    if restants == 0:
        EPUISES.add(lien_id)
        NOTIF.dernier_telechargement(info["createur"], lien_id, info["doc_id"])

    # 4. Le document tel qu'il est MAINTENANT (contrainte 3)
    texte, version = entree["doc"].instantane()
    cle = _cle_pdf(info["doc_id"], version)

    # 5. PDF deja pret : on le donne. Sinon : "patiente" + ticket.
    if STOCK.existe(cle):
        return _servir(cle, info["doc_id"])
    _lancer_fabrication(cle, entree["titre"], texte)
    ticket = uuid.uuid4().hex
    TICKETS[ticket] = {"cle": cle, "doc_id": info["doc_id"]}
    return _patiente(ticket, request)


@app.get("/telechargements/{ticket}")
def retirer_pdf(ticket: str, request: Request):
    t = TICKETS.get(ticket)
    if t is None:
        raise HTTPException(404, "Ticket inconnu")
    if STOCK.existe(t["cle"]):
        return _servir(t["cle"], t["doc_id"])
    if t["cle"] in EN_COURS:
        return _patiente(ticket, request)
    if STOCK.existe(t["cle"]):               # la fabrication s'est terminee entre-temps
        return _servir(t["cle"], t["doc_id"])
    raise HTTPException(500, "La fabrication du PDF a echoue")


# ---------------------------------------------------------------- administration

@app.get("/admin/bloques")
def admin_bloques(x_admin_token: str = Header(default="")):
    _admin(x_admin_token)
    return {"bloques": BLOCAGE.liste()}


@app.get("/admin/notifications")
def admin_notifications(x_admin_token: str = Header(default="")):
    _admin(x_admin_token)
    return {"notifications": NOTIF.liste()}


@app.get("/admin/etat")
def admin_etat(x_admin_token: str = Header(default="")):
    _admin(x_admin_token)
    maintenant = time.time()

    documents = []
    for doc_id, e in list(DOCUMENTS.items()):
        _, version = e["doc"].instantane()
        depuis = int(maintenant - e["derniere_activite"])
        connectes = len(SALLES.get(doc_id, ()))
        documents.append({
            "id": doc_id,
            "titre": e["titre"],
            "createur": e["createur"],
            "membres": len(e["membres"]),
            "version": version,
            "connectes": connectes,
            "actif": connectes > 0 or depuis < 300,   # ouvert ou modifie depuis moins de 5 minutes
            "secondes_depuis_activite": depuis,
        })

    tous_les_liens = LIENS.lister()
    liens_actifs = [
        {
            "id": l["lien_id"],
            "document": l["doc_id"],
            "createur": l["createur"],
            "maximum": l["maximum"],
            "restants": l["restants"],
            "telechargements_faits": l["maximum"] - l["restants"],
        }
        for l in tous_les_liens if l["restants"] > 0
    ]

    return {
        "documents": {
            "total": len(documents),
            "actifs": sum(1 for d in documents if d["actif"]),
            "liste": documents,
        },
        "liens": {
            "actifs": liens_actifs,
            "epuises": sum(1 for l in tous_les_liens if l["restants"] <= 0),
        },
        "bloques": BLOCAGE.liste(),
        "pdf_en_cours_de_fabrication": len(EN_COURS),
    }
