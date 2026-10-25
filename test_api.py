import sys
import threading
import time

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
CREATEUR = "createur@exemple.fr"


def appel(methode, chemin, email=CREATEUR, **kw):
    return requests.request(
        methode, BASE + chemin, headers={"X-Email": email}, timeout=60, **kw
    )


def nouveau_doc(membres=()):
    r = appel("POST", "/documents", json={"titre": "test"})
    assert r.status_code == 201, r.text
    doc_id = r.json()["id"]
    for m in membres:
        r = appel("POST", f"/documents/{doc_id}/membres", json={"email": m})
        assert r.status_code == 201, r.text
    return doc_id


def rejouer(ops):
    texte = ""
    for o in ops:
        if o["kind"] == "ins":
            texte = texte[:o["pos"]] + o["text"] + texte[o["pos"]:]
        else:
            texte = texte[:o["pos"]] + texte[o["pos"] + o["length"]:]
    return texte


def test_securite_et_validation():
    doc = nouveau_doc()
    assert requests.get(BASE + f"/documents/{doc}").status_code == 401
    assert appel("GET", f"/documents/{doc}", email="intrus@exemple.fr").status_code == 403
    r = appel("POST", f"/documents/{doc}/ops",
              json={"base": 0, "op": {"kind": "del", "pos": 0, "length": 5}})
    assert r.status_code == 422                      # rien a supprimer
    r = appel("POST", f"/documents/{doc}/ops",
              json={"base": 99, "op": {"kind": "ins", "pos": 0, "text": "a"}})
    assert r.status_code == 422                      # version inconnue
    assert appel("GET", f"/documents/{doc}").json()["version"] == 0   # rien n'a change


def test_scenario_classique():
    camille, paul = "camille@exemple.fr", "paul@exemple.fr"
    doc = nouveau_doc([camille, paul])
    r = appel("POST", f"/documents/{doc}/ops",
              json={"base": 0, "op": {"kind": "ins", "pos": 0, "text": "ABCDEF"}})
    assert r.status_code == 200 and r.json()["version"] == 1, r.text
    # tous les deux voient la version 1 ; Camille supprime CD, Paul insere X entre C et D
    r1 = appel("POST", f"/documents/{doc}/ops", email=camille,
               json={"base": 1, "op": {"kind": "del", "pos": 2, "length": 2}})
    r2 = appel("POST", f"/documents/{doc}/ops", email=paul,
               json={"base": 1, "op": {"kind": "ins", "pos": 3, "text": "X"}})
    assert r1.status_code == 200 and r2.status_code == 200
    texte = appel("GET", f"/documents/{doc}").json()["texte"]
    assert texte == "ABXEF", texte


def test_meme_endroit(n=200):
    emails = [f"r{i:03d}@exemple.fr" for i in range(n)]
    doc = nouveau_doc(emails)
    jetons = [f"<{i:03d}>" for i in range(n)]
    barriere = threading.Barrier(n)
    codes = []

    def redacteur(i):
        barriere.wait()                              # tout le monde envoie en meme temps
        r = appel("POST", f"/documents/{doc}/ops", email=emails[i],
                  json={"base": 0, "op": {"kind": "ins", "pos": 0, "text": jetons[i]}})
        codes.append(r.status_code)

    fils = [threading.Thread(target=redacteur, args=(i,)) for i in range(n)]
    for f in fils:
        f.start()
    for f in fils:
        f.join()

    assert codes.count(200) == n, f"reponses : {sorted(set(codes))}"
    etat = appel("GET", f"/documents/{doc}").json()
    perdus = [j for j in jetons if j not in etat["texte"]]
    assert not perdus, f"modifications perdues : {perdus[:5]}"
    assert len(etat["texte"]) == 5 * n and etat["version"] == n
    journal = appel("GET", f"/documents/{doc}/ops?depuis=0").json()["ops"]
    assert rejouer(journal) == etat["texte"]         # une replique obtient le meme texte


if __name__ == "__main__":
    debut = time.time()
    test_securite_et_validation()
    print("OK  acces refuses (401/403) et requetes invalides refusees (422)")
    test_scenario_classique()
    print("OK  scenario classique via l'API : ABXEF")
    test_meme_endroit()
    print("OK  200 redacteurs au meme endroit : aucune modification perdue")
    print(f"duree : {time.time() - debut:.1f} s")
