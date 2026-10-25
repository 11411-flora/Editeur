import uuid
from dataclasses import asdict
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

import credit as credit_mod
from doc import Document, dele, ins

app = FastAPI(title="Editeur de documents partage")

# Un seul processus : cet etat est donc unique. (A remplacer par DynamoDB.)
DOCUMENTS = {}
CREDIT = credit_mod.creer()


class NouveauDocument(BaseModel):
    titre: str = Field(min_length=1, max_length=200)


class NouveauMembre(BaseModel):
    email: str = Field(min_length=3, max_length=200)


class OperationIn(BaseModel):
    kind: Literal["ins", "del"]
    pos: int = Field(ge=0)
    text: str = Field(default="", max_length=10_000)
    length: int = Field(default=0, ge=0, le=10_000)


class Soumission(BaseModel):
    base: int = Field(ge=0)      # version que voyait le redacteur
    op: OperationIn


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
