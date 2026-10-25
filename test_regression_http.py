import sys, time, uuid, threading
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import requests
from pypdf import PdfReader

B = sys.argv[1]; ADMIN = sys.argv[2]; BLOQUAGE_ACTIF = sys.argv[3] == "oui"
def ap(m, c, e, **kw): return requests.request(m, B + c, headers={"X-Email": e}, timeout=120, **kw)
def mail(p): return f"{p}-{uuid.uuid4().hex[:6]}@exemple.fr"

# --- ecriture HTTP : 200 redacteurs au meme endroit (la route est maintenant "async")
c = mail("c"); emails = [mail(f"r{i}") for i in range(200)]
doc = ap("POST", "/documents", c, json={"titre": "t"}).json()["id"]
for e in emails: ap("POST", f"/documents/{doc}/membres", c, json={"email": e})
bar = threading.Barrier(200); codes = []
def w(i):
    bar.wait()
    codes.append(ap("POST", f"/documents/{doc}/ops", emails[i], json={"base": 0, "op": {"kind": "ins", "pos": 0, "text": chr(0x4E00 + i)}}).status_code)
ts = [threading.Thread(target=w, args=(i,)) for i in range(200)]
[t.start() for t in ts]; [t.join() for t in ts]
etat = ap("GET", f"/documents/{doc}", c).json()
assert codes.count(200) == 200 and sorted(etat["texte"]) == sorted(chr(0x4E00 + i) for i in range(200)) and etat["version"] == 200
print("OK  HTTP : 200 redacteurs au meme endroit, aucune modification perdue")
assert ap("POST", f"/documents/{doc}/ops", c, json={"base": 200, "op": {"kind": "ins", "pos": 0, "text": "\U0001F600"}}).status_code == 422
print("OK  les emojis sont refuses proprement (422)")

# --- liens : 500 exemplaires, 1500 visiteurs
d2 = ap("POST", "/documents", c, json={"titre": "Journal"}).json()["id"]
ap("POST", f"/documents/{d2}/ops", c, json={"base": 0, "op": {"kind": "ins", "pos": 0, "text": "Journal de l'association"}})
lien = ap("POST", f"/documents/{d2}/liens", c, json={"max_telechargements": 500}).json()["id"]
def visiter(_):
    r = requests.get(f"{B}/liens/{lien}", timeout=120)
    if r.status_code == 410: return "epuise"
    deb = time.time()
    while r.status_code == 202:
        assert time.time() - deb < 60
        time.sleep(1); r = requests.get(B + r.headers["Location"], timeout=120)
    assert r.status_code == 200 and r.content.startswith(b"%PDF"), r.status_code
    return "pdf"
t0 = time.time()
with ThreadPoolExecutor(max_workers=100) as p: res = list(p.map(visiter, range(1500)))
assert res.count("pdf") == 500 and res.count("epuise") == 1000, (res.count("pdf"), res.count("epuise"))
print(f"OK  liens : exactement 500 PDF sur 1500 visiteurs ({time.time()-t0:.1f} s)")
mails = requests.get(B + "/admin/notifications", headers={"X-Admin-Token": ADMIN}).json()["notifications"]
assert len([m for m in mails if m["lien_id"] == lien]) == 1
print("OK  un seul e-mail au dernier telechargement")
ap("POST", f"/documents/{d2}/ops", c, json={"base": 1, "op": {"kind": "ins", "pos": 24, "text": " et suite"}})
l2 = ap("POST", f"/documents/{d2}/liens", c, json={"max_telechargements": 3}).json()["id"]
r = requests.get(f"{B}/liens/{l2}")
while r.status_code == 202: time.sleep(1); r = requests.get(B + r.headers["Location"])
txt = "".join(p.extract_text() for p in PdfReader(BytesIO(r.content)).pages).replace(" ", "").replace("\n", "")
assert "etsuite" in txt, txt
print("OK  le PDF contient la version actuelle du document")

e = requests.get(B + "/admin/etat", headers={"X-Admin-Token": ADMIN}).json()
assert e["documents"]["total"] >= 2 and "connectes" in e["documents"]["liste"][0]
print("OK  /admin/etat repond (documents, liens, bloques, connectes)")

if BLOQUAGE_ACTIF:
    a = mail("acharne"); dd = ap("POST", "/documents", a, json={"titre": "abus"}).json()["id"]
    assert ap("POST", f"/documents/{dd}/ops", a, json={"base": 0, "op": {"kind": "ins", "pos": 0, "text": "a" * 10000}}).status_code == 200
    for i in range(4):
        r = ap("POST", f"/documents/{dd}/ops", a, json={"base": 1, "op": {"kind": "ins", "pos": 0, "text": "b"}})
        assert r.status_code == 429 and r.json()["detail"]["erreur"] == "credit_epuise"
    r = ap("POST", f"/documents/{dd}/ops", a, json={"base": 1, "op": {"kind": "ins", "pos": 0, "text": "b"}})
    assert r.status_code == 429 and r.json()["detail"]["erreur"] == "bloque" and int(r.headers["Retry-After"]) > 0
    assert a in requests.get(B + "/admin/bloques", headers={"X-Admin-Token": ADMIN}).json()["bloques"]
    print("OK  blocage : 4 refus 'credit_epuise', le 5e bloque, visible dans /admin/bloques")
