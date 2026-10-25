import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import requests
from pypdf import PdfReader

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
ADMIN = os.environ.get("ADMIN_TOKEN", "")
N_LIEN = int(sys.argv[1]) if len(sys.argv) > 1 else 500
N_VISITEURS = int(sys.argv[2]) if len(sys.argv) > 2 else 1500


def appel(methode, chemin, email, **kw):
    return requests.request(methode, BASE + chemin, headers={"X-Email": email}, timeout=60, **kw)


def email_neuf(prefixe):
    return f"{prefixe}-{uuid.uuid4().hex[:6]}@exemple.fr"


def nouveau_doc(email, texte):
    doc = appel("POST", "/documents", email, json={"titre": "Journal"}).json()["id"]
    r = appel("POST", f"/documents/{doc}/ops", email,
              json={"base": 0, "op": {"kind": "ins", "pos": 0, "text": texte}})
    assert r.status_code == 200, r.text
    return doc


def creer_lien(doc, email, n):
    r = appel("POST", f"/documents/{doc}/liens", email, json={"max_telechargements": n})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def visiter(lien):
    """Un visiteur clique. Renvoie (ce qu'on lui a dit d'abord, octets du PDF ou None)."""
    r = requests.get(f"{BASE}/liens/{lien}", timeout=120)
    if r.status_code == 410:
        return "epuise", None
    assert r.status_code in (200, 202), (r.status_code, r.text[:200])
    premier = "maintenant" if r.status_code == 200 else "patiente"
    debut = time.time()
    while r.status_code == 202:
        assert time.time() - debut < 60, "le PDF n'est jamais devenu pret"
        time.sleep(float(r.headers.get("Retry-After", "1")))
        r = requests.get(BASE + r.headers["Location"], timeout=120)
    assert r.status_code == 200, (r.status_code, r.text[:200])
    assert r.content.startswith(b"%PDF")
    return premier, r.content


def texte_pdf(octets):
    lecteur = PdfReader(BytesIO(octets))
    texte = "".join(p.extract_text() or "" for p in lecteur.pages)
    return texte.replace(" ", "").replace("\n", "")


def test_exactement_n():
    email = email_neuf("createur")
    doc = nouveau_doc(email, "Journal de l'association")
    lien = creer_lien(doc, email, N_LIEN)
    debut = time.time()
    with ThreadPoolExecutor(max_workers=100) as pool:
        resultats = list(pool.map(lambda _: visiter(lien), range(N_VISITEURS)))
    duree = time.time() - debut
    etats = [e for e, _ in resultats]
    pdfs = [c for _, c in resultats if c is not None]
    attendus = min(N_LIEN, N_VISITEURS)
    assert len(pdfs) == attendus, f"{len(pdfs)} PDF livres au lieu de {attendus}"
    assert etats.count("epuise") == N_VISITEURS - attendus
    # les visiteurs en retard apprennent vite que c'est epuise
    t0 = time.time()
    for _ in range(100):
        r = requests.get(f"{BASE}/liens/{lien}", timeout=30)
        assert r.status_code == 410 and r.json()["etat"] == "epuise"
    ms = (time.time() - t0) / 100 * 1000
    return etats, len(pdfs), duree, ms


def test_version_actuelle():
    email = email_neuf("version")
    doc = nouveau_doc(email, "Version un")
    lien = creer_lien(doc, email, 5)
    _, pdf1 = visiter(lien)
    t1 = texte_pdf(pdf1)
    assert "Versionun" in t1 and "deux" not in t1, t1
    r = appel("POST", f"/documents/{doc}/ops", email,
              json={"base": 1, "op": {"kind": "ins", "pos": 10, "text": " et deux"}})
    assert r.status_code == 200, r.text
    _, pdf2 = visiter(lien)                                  # MEME lien, document modifie
    assert "Versionunetdeux" in texte_pdf(pdf2), texte_pdf(pdf2)


def test_un_seul_email():
    email = email_neuf("mail")
    doc = nouveau_doc(email, "bonjour")
    lien = creer_lien(doc, email, 3)
    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(lambda _: visiter(lien), range(10)))
    r = requests.get(BASE + "/admin/notifications", headers={"X-Admin-Token": ADMIN}, timeout=30)
    assert r.status_code == 200, r.text
    mails = [m for m in r.json()["notifications"] if m["lien_id"] == lien]
    assert len(mails) == 1, f"{len(mails)} e-mails au lieu de 1"
    assert mails[0]["destinataire"] == email


def test_erreurs():
    email = email_neuf("err")
    doc = nouveau_doc(email, "x")
    assert requests.get(f"{BASE}/liens/inconnu", timeout=30).status_code == 404
    assert appel("POST", f"/documents/{doc}/liens", "intrus@exemple.fr",
                 json={"max_telechargements": 5}).status_code == 403
    assert appel("POST", f"/documents/{doc}/liens", email,
                 json={"max_telechargements": 0}).status_code == 422


if __name__ == "__main__":
    etats, livres, duree, ms = test_exactement_n()
    print(f"OK  lien de {N_LIEN}, {N_VISITEURS} visiteurs : {livres} PDF livres, "
          f"{etats.count('epuise')} 'epuise'")
    print(f"    reponses initiales : {etats.count('maintenant')} 'maintenant', "
          f"{etats.count('patiente')} 'patiente', {etats.count('epuise')} 'epuise'")
    print(f"    duree totale : {duree:.1f} s ; reponse 'epuise' apres coup : {ms:.0f} ms en moyenne")
    test_version_actuelle()
    print("OK  le meme lien donne le document tel qu'il est au moment du clic")
    test_un_seul_email()
    print("OK  exactement un e-mail au createur, au dernier telechargement")
    test_erreurs()
    print("OK  lien inconnu (404), intrus (403), nombre invalide (422)")
