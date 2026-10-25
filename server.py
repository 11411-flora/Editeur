import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

import blocage as blocage_mod
import credit as credit_mod
import liens as liens_mod
import notifications as notif_mod
import pdfgen
import stockage_pdf
from doc import Document, dele, ins

log = logging.getLogger("editeur")
app = FastAPI(title="Editeur de documents partage")

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

@app.post("/documents", status_code=201)
def creer_document(corps: NouveauDocument, x_email: str = Header(default="")):
    email = _email(x_email)
    doc_id = uuid.uuid4().hex[:10]
    DOCUMENTS[doc_id] = {
        "doc": Document(),
        "titre": corps.titre,
        "createur": email,
        "membres": {email},
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


@app.post("/documents/{doc_id}/ops")
def soumettre(doc_id: str, corps: Soumission, x_email: str = Header(default="")):
    email = _email(x_email)
    entree = _document(doc_id, email)

    # deja bloque ? on repond tout de suite, sans toucher au credit
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

    restant = CREDIT.limite - CREDIT.utilises(email, jour)
    # "ops" peut etre vide : tout ce que tu supprimais l'etait deja
    return {
        "version": version,
        "ops": [asdict(a) for a in acceptees],
        "credit_restant": restant,
    }


@app.get("/documents/{doc_id}/ops")
def lire_ops(doc_id: str, depuis: int = 0, x_email: str = Header(default="")):
    entree = _document(doc_id, _email(x_email))
    depuis = max(0, depuis)
    ops, version = entree["doc"].journal_depuis(depuis)
    return {"depuis": depuis, "version": version, "ops": [asdict(o) for o in ops]}


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


def _patiente(ticket):
    return JSONResponse(
        status_code=202,
        content={"etat": "patiente", "ticket": ticket, "reessayer_dans_s": 1},
        headers={"Retry-After": "1", "Location": f"/telechargements/{ticket}"},
    )


def _epuise():
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
def utiliser_lien(lien_id: str):
    # 1. On sait deja que c'est epuise : reponse immediate, sans toucher a la base
    if lien_id in EPUISES:
        return _epuise()

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
        return _epuise()

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
    return _patiente(ticket)


@app.get("/telechargements/{ticket}")
def retirer_pdf(ticket: str):
    t = TICKETS.get(ticket)
    if t is None:
        raise HTTPException(404, "Ticket inconnu")
    if STOCK.existe(t["cle"]):
        return _servir(t["cle"], t["doc_id"])
    if t["cle"] in EN_COURS:
        return _patiente(ticket)
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
