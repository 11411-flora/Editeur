import os
import time
import uuid

import requests

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
ADMIN = os.environ["ADMIN_TOKEN"]


def appel(methode, chemin, email, **kw):
    return requests.request(methode, BASE + chemin, headers={"X-Email": email}, timeout=60, **kw)


def etat():
    r = requests.get(BASE + "/admin/etat", headers={"X-Admin-Token": ADMIN}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def telecharger(lien):
    r = requests.get(f"{BASE}/liens/{lien}", timeout=60)
    debut = time.time()
    while r.status_code == 202:
        assert time.time() - debut < 30
        time.sleep(1)
        r = requests.get(BASE + r.headers["Location"], timeout=60)
    return r.status_code


assert requests.get(BASE + "/admin/etat", timeout=30).status_code == 403
print("OK  sans jeton d'administration : acces refuse (403)")

createur = f"createur-{uuid.uuid4().hex[:6]}@exemple.fr"
doc = appel("POST", "/documents", createur, json={"titre": "Journal d'etat"}).json()["id"]
assert appel("POST", f"/documents/{doc}/ops", createur,
             json={"base": 0, "op": {"kind": "ins", "pos": 0, "text": "bonjour"}}).status_code == 200

e = etat()
fiche = next(d for d in e["documents"]["liste"] if d["id"] == doc)
assert fiche["actif"] and fiche["version"] == 1 and fiche["createur"] == createur
print("OK  le document apparait, actif, version 1")

lien = appel("POST", f"/documents/{doc}/liens", createur, json={"max_telechargements": 3}).json()["id"]
assert telecharger(lien) == 200 and telecharger(lien) == 200
e = etat()
fiche = next(l for l in e["liens"]["actifs"] if l["id"] == lien)
assert fiche["restants"] == 1 and fiche["telechargements_faits"] == 2 and fiche["maximum"] == 3
print("OK  le lien actif montre 1 telechargement restant (2 faits sur 3)")

assert telecharger(lien) == 200
assert telecharger(lien) == 410
e = etat()
assert all(l["id"] != lien for l in e["liens"]["actifs"])
assert e["liens"]["epuises"] >= 1
print("OK  une fois epuise, le lien quitte la liste des liens actifs")

acharne = f"acharne-{uuid.uuid4().hex[:6]}@exemple.fr"
d2 = appel("POST", "/documents", acharne, json={"titre": "abus"}).json()["id"]
assert appel("POST", f"/documents/{d2}/ops", acharne,
             json={"base": 0, "op": {"kind": "ins", "pos": 0, "text": "a" * 10_000}}).status_code == 200
for _ in range(5):
    appel("POST", f"/documents/{d2}/ops", acharne,
          json={"base": 1, "op": {"kind": "ins", "pos": 0, "text": "b"}})
e = etat()
assert acharne in e["bloques"] and createur not in e["bloques"]
print(f"OK  la personne bloquee apparait avec son temps restant ({e['bloques'][acharne]} s)")
