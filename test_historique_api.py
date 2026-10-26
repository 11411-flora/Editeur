import asyncio, json, os, sys, time, uuid
import requests
import websockets

B = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
ADMIN = os.environ.get("ADMIN_TOKEN", "")
def ap(m, c, e, **kw): return requests.request(m, B + c, headers={"X-Email": e}, timeout=60, **kw)
def mail(p): return f"{p}-{uuid.uuid4().hex[:6]}@exemple.fr"
def ecrire(doc, e, base, op): 
    r = ap("POST", f"/documents/{doc}/ops", e, json={"base": base, "op": op}); assert r.status_code == 200, r.text; return r.json()

c = mail("c")
doc = ap("POST", "/documents", c, json={"titre": "histo"}).json()["id"]
ecrire(doc, c, 0, {"kind": "ins", "pos": 0, "text": "Bonjour"})
ecrire(doc, c, 1, {"kind": "ins", "pos": 7, "text": " monde"})
ecrire(doc, c, 2, {"kind": "del", "pos": 0, "length": 3})
def texte_v(n): return ap("GET", f"/documents/{doc}/versions/{n}", c).json()["texte"]
assert [texte_v(n) for n in range(4)] == ["", "Bonjour", "Bonjour monde", "jour monde"]
assert ap("GET", f"/documents/{doc}/versions/99", c).status_code == 404
v = ap("GET", f"/documents/{doc}/versions", c).json()
assert v["courante"] == 3 and v["recentes"] == [0, 1, 2, 3]
print("OK  chaque version est consultable : '', 'Bonjour', 'Bonjour monde', 'jour monde' ; version inconnue = 404")

avant = ap("GET", "/credit", c).json()["utilises"]
r = ap("POST", f"/documents/{doc}/restaurer", c, json={"version": 1})
assert r.status_code == 200 and r.json()["restaure"] == 1, r.text
assert ap("GET", f"/documents/{doc}", c).json()["texte"] == "Bonjour"
assert texte_v(3) == "jour monde" and texte_v(2) == "Bonjour monde"      # l'historique n'est pas reecrit
apres = ap("GET", "/credit", c).json()["utilises"]
assert apres - avant == len("Bonjour")
nouvelle = ap("GET", f"/documents/{doc}/versions", c).json()["courante"]
assert nouvelle > 3 and texte_v(nouvelle) == "Bonjour"
print(f"OK  restaurer la version 1 : texte 'Bonjour', anciennes versions intactes, nouvelle version {nouvelle}, credit -{apres-avant}")

assert ap("POST", f"/documents/{doc}/restaurer", c, json={"version": 0}).status_code == 200
assert ap("GET", f"/documents/{doc}", c).json()["texte"] == ""
assert ap("POST", f"/documents/{doc}/restaurer", c, json={"version": 9999}).status_code == 404
assert ap("POST", f"/documents/{doc}/restaurer", mail("intrus"), json={"version": 1}).status_code == 403
assert ap("GET", f"/documents/{doc}/versions/1", mail("intrus")).status_code == 403
print("OK  restaurer la version 0 vide le document ; version inconnue = 404 ; intrus = 403")

# une restauration est diffusee en temps reel
async def diffusion():
    autre = mail("autre"); ap("POST", f"/documents/{doc}/membres", c, json={"email": autre})
    ws_url = B.replace("http", "ws", 1) + f"/documents/{doc}/live?email={autre}&nom=Autre"
    async with websockets.connect(ws_url) as w:
        etat = {"type": None}
        while etat["type"] != "etat": etat = json.loads(await asyncio.wait_for(w.recv(), 5))
        texte = etat["texte"]
        ecrire(doc, c, ap("GET", f"/documents/{doc}", c).json()["version"], {"kind": "ins", "pos": 0, "text": "xyz"})
        ap("POST", f"/documents/{doc}/restaurer", c, json={"version": 1})
        for _ in range(10):
            m = json.loads(await asyncio.wait_for(w.recv(), 5))
            if m["type"] == "ops":
                for o in m["ops"]:
                    texte = texte[:o["pos"]] + o["text"] + texte[o["pos"]:] if o["kind"] == "ins" else texte[:o["pos"]] + texte[o["pos"] + o["length"]:]
                if texte == "Bonjour": return
        raise AssertionError("la restauration n'a pas ete diffusee : " + texte)
asyncio.run(diffusion())
print("OK  une restauration apparait en temps reel chez les autres connectes")

# lien ouvert dans un navigateur : page qui se rafraichit toute seule, un seul exemplaire consomme
lien = ap("POST", f"/documents/{doc}/liens", c, json={"max_telechargements": 2}).json()["id"]
ecrire(doc, c, ap("GET", f"/documents/{doc}", c).json()["version"], {"kind": "ins", "pos": 0, "text": "Texte pour le PDF "})
nav = {"Accept": "text/html,application/xhtml+xml"}
r = requests.get(f"{B}/liens/{lien}", headers=nav)
if r.status_code == 202:
    assert "text/html" in r.headers["content-type"] and 'http-equiv="refresh"' in r.text
    ticket_url = r.text.split("url=")[1].split('"')[0]
    for _ in range(30):
        r = requests.get(B + ticket_url, headers=nav)
        if r.status_code == 200: break
        assert r.status_code == 202; time.sleep(0.5)
assert r.status_code == 200 and r.content.startswith(b"%PDF")
if ADMIN:
    liens = requests.get(B + "/admin/etat", headers={"X-Admin-Token": ADMIN}).json()["liens"]["actifs"]
    mien = [l for l in liens if l["id"] == lien][0]
    assert mien["restants"] == 1, mien
r = requests.get(f"{B}/liens/{lien}", headers=nav)                        # 2e et dernier exemplaire
while r.status_code == 202:
    time.sleep(0.5); r = requests.get(B + r.text.split("url=")[1].split('"')[0], headers=nav)
r = requests.get(f"{B}/liens/{lien}", headers=nav)
assert r.status_code == 410 and "text/html" in r.headers["content-type"] and "puis" in r.text
assert requests.get(f"{B}/liens/{lien}").json()["etat"] == "epuise"        # sans Accept html : toujours du JSON
print("OK  navigateur : la page se rafraichit seule (un seul exemplaire consomme), puis page 'epuise' lisible ; clients JSON inchanges")
