import random
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def appel(methode, chemin, email, **kw):
    return requests.request(
        methode, BASE + chemin, headers={"X-Email": email}, timeout=60, **kw
    )


def email_neuf(prefixe):
    return f"{prefixe}-{uuid.uuid4().hex[:8]}@exemple.fr"


def nouveau_doc(email):
    r = appel("POST", "/documents", email, json={"titre": "credit"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def inserer(doc, email, texte, base=0):
    return appel("POST", f"/documents/{doc}/ops", email,
                 json={"base": base, "op": {"kind": "ins", "pos": 0, "text": texte}})


def credit(email):
    return appel("GET", "/credit", email).json()


def test_plusieurs_appareils():
    email = email_neuf("multi")
    doc = nouveau_doc(email)
    limite = credit(email)["limite"]
    random.seed(3)
    tailles = [random.randint(10, 200) for _ in range(150)]
    assert sum(tailles) > limite, "le test doit demander plus que la limite"

    def appareil(n):
        r = inserer(doc, email, "a" * n)
        assert r.status_code in (200, 429), r.text
        return n if r.status_code == 200 else 0

    with ThreadPoolExecutor(max_workers=20) as pool:      # 20 appareils a la fois
        acceptes = sum(pool.map(appareil, tailles))

    etat = appel("GET", f"/documents/{doc}", email).json()
    assert acceptes <= limite, f"credit depasse : {acceptes}"
    assert len(etat["texte"]) == acceptes, "le texte ne correspond pas a ce qui est accepte"
    assert credit(email)["utilises"] == acceptes

    # on vide exactement le credit, puis plus rien ne passe
    reste = limite - acceptes
    if reste > 0:
        assert inserer(doc, email, "z" * reste, base=etat["version"]).status_code == 200
    assert inserer(doc, email, "y").status_code == 429
    assert credit(email)["restant"] == 0

    # supprimer est gratuit, meme avec un credit a zero
    etat = appel("GET", f"/documents/{doc}", email).json()
    r = appel("POST", f"/documents/{doc}/ops", email,
              json={"base": etat["version"], "op": {"kind": "del", "pos": 0, "length": 1}})
    assert r.status_code == 200, r.text
    assert credit(email)["utilises"] == limite
    return acceptes, sum(tailles)


def test_autre_redacteur_non_touche():
    autre = email_neuf("autre")
    doc = nouveau_doc(autre)
    assert inserer(doc, autre, "bonjour").status_code == 200
    assert credit(autre)["utilises"] == 7


def test_erreur_remboursee():
    email = email_neuf("erreur")
    doc = nouveau_doc(email)
    r = inserer(doc, email, "abcde", base=99)       # version inconnue
    assert r.status_code == 422, r.text
    assert credit(email)["utilises"] == 0           # rien n'a ete debite


if __name__ == "__main__":
    debut = time.time()
    acceptes, demandes = test_plusieurs_appareils()
    print(f"OK  20 appareils : {demandes} caracteres demandes, {acceptes} acceptes, jamais plus de 10 000")
    print("OK  credit vide exactement, puis refus 429 ; supprimer reste gratuit")
    test_autre_redacteur_non_touche()
    print("OK  un autre redacteur n'est pas touche")
    test_erreur_remboursee()
    print("OK  une modification invalide ne coute rien")
    print(f"duree : {time.time() - debut:.1f} s")
