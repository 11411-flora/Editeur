import asyncio
import json
import random
import sys
import uuid

import requests
import websockets

HTTP = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
WS = HTTP.replace("http", "ws", 1)


def api(methode, chemin, email, **kw):
    return requests.request(methode, HTTP + chemin, headers={"X-Email": email}, timeout=60, **kw)


def email_neuf(p):
    return f"{p}-{uuid.uuid4().hex[:6]}@exemple.fr"


def nouveau_doc(email, membres=()):
    doc = api("POST", "/documents", email, json={"titre": "ws"}).json()["id"]
    for m in membres:
        assert api("POST", f"/documents/{doc}/membres", email, json={"email": m}).status_code == 201
    return doc


def url(doc, email, nom="Anonyme"):
    return f"{WS}/documents/{doc}/live?email={email}&nom={nom}"


async def recevoir(ws, genre, delai=10):
    """Lit les messages jusqu'a trouver un message du type demande."""
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), delai))
        if msg["type"] == genre:
            return msg


def appliquer(t, o):
    if o["kind"] == "ins":
        return t[:o["pos"]] + o["text"] + t[o["pos"]:]
    return t[:o["pos"]] + t[o["pos"] + o["length"]:]


async def test_acces():
    a, intrus = email_neuf("a"), email_neuf("intrus")
    doc = nouveau_doc(a)
    for adresse in (url(doc, intrus), url("inconnu", a), f"{WS}/documents/{doc}/live?email=pasunemail"):
        try:
            async with websockets.connect(adresse):
                raise AssertionError("la connexion aurait du etre refusee")
        except AssertionError:
            raise
        except Exception:
            pass
    print("OK  connexion refusee : non-membre, document inconnu, e-mail invalide")


async def test_ack_et_diffusion():
    a, b = email_neuf("a"), email_neuf("b")
    doc = nouveau_doc(a, [b])
    async with websockets.connect(url(doc, a, "Camille")) as wa, websockets.connect(url(doc, b, "Paul")) as wb:
        ea, eb = await recevoir(wa, "etat"), await recevoir(wb, "etat")
        assert ea["texte"] == "" and ea["version"] == 0 and eb["version"] == 0
        pres = await recevoir(wb, "presence")
        while len(pres["utilisateurs"]) < 2:
            pres = await recevoir(wb, "presence")
        assert {u["nom"] for u in pres["utilisateurs"]} == {"Camille", "Paul"}
        print("OK  a la connexion : etat du document + liste des presents (Camille, Paul)")

        await wa.send(json.dumps({"type": "op", "base": 0, "op": {"kind": "ins", "pos": 0, "text": "Bonjour"}}))
        ack = await recevoir(wa, "ack")
        ops = await recevoir(wb, "ops")
        assert ack["version"] == 1 and ack["ops"] == ops["ops"] and ops["auteur"] == a
        assert ack["credit_restant"] == 10_000 - 7
        print("OK  l'auteur recoit un accuse (ack), l'autre redacteur recoit les operations")

        # une modification faite par l'API HTTP est aussi diffusee en temps reel
        r = api("POST", f"/documents/{doc}/ops", b,
                json={"base": 1, "op": {"kind": "ins", "pos": 7, "text": "!"}})
        assert r.status_code == 200
        recu = await recevoir(wa, "ops")
        assert recu["ops"][0]["text"] == "!" and recu["version"] == 2
        print("OK  une modification envoyee par l'API HTTP apparait en temps reel chez les connectes")

        await wb.send(json.dumps({"type": "curseur", "pos": 3}))
        p = await recevoir(wa, "presence")
        while not any(u["curseur"] == 3 for u in p["utilisateurs"]):
            p = await recevoir(wa, "presence")
        print("OK  la position du curseur de Paul est diffusee")
    await asyncio.sleep(0.3)


async def test_erreurs_et_sync():
    a = email_neuf("a")
    doc = nouveau_doc(a)
    async with websockets.connect(url(doc, a)) as w:
        await recevoir(w, "etat")
        await w.send(json.dumps({"type": "op", "base": 0, "op": {"kind": "ins", "pos": 0, "text": "a" * 10_000}}))
        await recevoir(w, "ack")
        await w.send(json.dumps({"type": "op", "base": 1, "op": {"kind": "ins", "pos": 0, "text": "b"}}))
        err = await recevoir(w, "erreur")
        assert err["code"] == 429 and err["detail"]["erreur"] == "credit_epuise"
        await w.send(json.dumps({"type": "op", "base": 99, "op": {"kind": "del", "pos": 0, "length": 1}}))
        err = await recevoir(w, "erreur")
        assert err["code"] == 422
        await w.send("pas du json")
        err = await recevoir(w, "erreur")
        assert err["code"] == 400
        await w.send(json.dumps({"type": "sync"}))
        etat = await recevoir(w, "etat")
        assert etat["version"] == 1 and len(etat["texte"]) == 10_000
        print("OK  erreurs (429 credit, 422 version, 400 JSON) renvoyees ; 'sync' redonne l'etat officiel")


async def client_verrouille(doc, email, i, nb_ops, graine, resultats):
    """Un redacteur qui envoie ses modifications une par une, comme le sujet l'impose."""
    rnd = random.Random(graine)
    async with websockets.connect(url(doc, email)) as ws:
        etat = await recevoir(ws, "etat")
        t, v = etat["texte"], etat["version"]
        for k in range(nb_ops):
            jeton = chr(0x4E00 + i * nb_ops + k)      # un caractere unique : impossible a couper
            await ws.send(json.dumps({"type": "op", "base": v,
                                      "op": {"kind": "ins", "pos": rnd.randint(0, len(t)), "text": jeton}}))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 30))
                if msg["type"] == "ops":
                    for o in msg["ops"]:
                        t = appliquer(t, o)
                    v = msg["version"]
                elif msg["type"] == "ack":
                    for o in msg["ops"]:
                        t = appliquer(t, o)
                    v = msg["version"]
                    break
                elif msg["type"] == "erreur":
                    raise AssertionError(msg)
        # on continue d'ecouter jusqu'a ce que tout se calme
        while True:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 1.5))
            except asyncio.TimeoutError:
                break
            if msg["type"] == "ops":
                for o in msg["ops"]:
                    t = appliquer(t, o)
                v = msg["version"]
        resultats[i] = (t, v)


async def test_convergence(n_clients=30, nb_ops=8):
    emails = [email_neuf(f"r{i}") for i in range(n_clients)]
    doc = nouveau_doc(emails[0], emails[1:])
    resultats = {}
    await asyncio.gather(*[
        client_verrouille(doc, emails[i], i, nb_ops, 1000 + i, resultats) for i in range(n_clients)])
    final = api("GET", f"/documents/{doc}", emails[0]).json()
    assert final["version"] == n_clients * nb_ops
    divergents = [i for i, (t, v) in resultats.items() if t != final["texte"] or v != final["version"]]
    assert not divergents, f"clients qui divergent : {divergents}"
    attendus = [chr(0x4E00 + i * nb_ops + k) for i in range(n_clients) for k in range(nb_ops)]
    perdus = [c for c in attendus if final["texte"].count(c) != 1]
    assert not perdus, f"modifications perdues ou doublees : {len(perdus)}"
    print(f"OK  {n_clients} redacteurs connectes x {nb_ops} modifications chacun, au meme document : "
          f"aucune perdue, tous voient le meme texte ({len(final['texte'])} caracteres)")


async def main():
    await test_acces()
    await test_ack_et_diffusion()
    await test_erreurs_et_sync()
    await test_convergence()


asyncio.run(main())
