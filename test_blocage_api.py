import os
import sys
import uuid

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
ADMIN = os.environ["ADMIN_TOKEN"]       # le meme jeton que celui du serveur


def appel(methode, chemin, email, **kw):
    return requests.request(methode, BASE + chemin, headers={"X-Email": email}, timeout=60, **kw)


def inserer(doc, email, texte):
    return appel("POST", f"/documents/{doc}/ops", email,
                 json={"base": 0, "op": {"kind": "ins", "pos": 0, "text": texte}})


email = f"acharne-{uuid.uuid4().hex[:8]}@exemple.fr"
autre = f"calme-{uuid.uuid4().hex[:8]}@exemple.fr"
doc = appel("POST", "/documents", email, json={"titre": "abus"}).json()["id"]

# on epuise exactement le credit (valeurs par defaut : 10 000 caracteres)
assert inserer(doc, email, "a" * 10_000).status_code == 200

# refus 1 a 4 : "credit_epuise", pas encore bloque
for i in range(4):
    r = inserer(doc, email, "b")
    assert r.status_code == 429 and r.json()["detail"]["erreur"] == "credit_epuise", r.text
print("OK  4 refus de credit : toujours seulement 'credit_epuise'")

# le 5e declenche le blocage
r = inserer(doc, email, "b")
assert r.status_code == 429 and r.json()["detail"]["erreur"] == "bloque", r.text
assert int(r.headers["Retry-After"]) > 0
print(f"OK  5e refus : bloque, Retry-After = {r.headers['Retry-After']} s")

# bloque : tout essai d'ecriture est refuse, meme une suppression
r = appel("POST", f"/documents/{doc}/ops", email,
          json={"base": 1, "op": {"kind": "del", "pos": 0, "length": 1}})
assert r.status_code == 429 and r.json()["detail"]["erreur"] == "bloque", r.text
print("OK  pendant le blocage, l'ecriture reste refusee")

# lire reste possible
assert appel("GET", f"/documents/{doc}", email).status_code == 200
print("OK  lire reste possible")

# un autre redacteur n'est pas touche
doc2 = appel("POST", "/documents", autre, json={"titre": "calme"}).json()["id"]
assert inserer(doc2, autre, "bonjour").status_code == 200
print("OK  un autre redacteur peut ecrire")

# la vue de l'association
assert requests.get(BASE + "/admin/bloques", timeout=30).status_code == 403
r = requests.get(BASE + "/admin/bloques", headers={"X-Admin-Token": ADMIN}, timeout=30)
assert r.status_code == 200 and email in r.json()["bloques"], r.text
assert autre not in r.json()["bloques"]
print("OK  /admin/bloques liste la personne bloquee (et seulement elle)")
