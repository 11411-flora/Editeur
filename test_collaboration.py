import random
import threading
import time

from doc import Document, appliquer, dele, ins


def rejouer(journal, depart=""):
    texte = depart
    for op in journal:
        texte = appliquer(texte, op)
    return texte


def test_scenario_classique():
    # Camille supprime "CD", Paul insere "X" entre C et D, meme version de depart
    d = Document("ABCDEF")
    d.soumettre(dele(2, 2), 0)
    d.soumettre(ins(3, "X"), 0)
    assert d.texte == "ABXEF", d.texte
    # meme chose dans l'autre ordre d'arrivee
    d = Document("ABCDEF")
    d.soumettre(ins(3, "X"), 0)
    d.soumettre(dele(2, 2), 0)
    assert d.texte == "ABXEF", d.texte


def test_meme_endroit_300_redacteurs():
    d = Document("")
    n = 300
    jetons = [f"<{i:03d}>" for i in range(n)]
    barriere = threading.Barrier(n)

    def redacteur(jeton):
        barriere.wait()                     # tout le monde ecrit en meme temps
        d.soumettre(ins(0, jeton), 0)       # tous voient la version 0

    fils = [threading.Thread(target=redacteur, args=(j,)) for j in jetons]
    for f in fils:
        f.start()
    for f in fils:
        f.join()

    perdus = [j for j in jetons if j not in d.texte]
    assert not perdus, f"modifications perdues : {perdus[:5]}"
    assert len(d.texte) == 5 * n
    assert d.version == n
    assert rejouer(d.journal) == d.texte    # une replique obtient le meme texte


def test_aleatoire(n_ops=5000, graine=1):
    rnd = random.Random(graine)
    depart = "0123456789"
    d = Document(depart)
    textes = [depart]                       # textes[v] = texte a la version v
    for _ in range(n_ops):
        v = rnd.randint(max(0, d.version - 5), d.version)   # redacteur en retard
        t = textes[v]
        if rnd.random() < 0.6 or not t:
            op = ins(rnd.randint(0, len(t)),
                     rnd.choice("abcdefgh") * rnd.randint(1, 3))
        else:
            p = rnd.randint(0, len(t) - 1)
            op = dele(p, rnd.randint(1, min(4, len(t) - p)))
        d.soumettre(op, v)                  # leve ValueError si une position est fausse
        courant = textes[-1]
        for o in d.journal[len(textes) - 1:]:
            courant = appliquer(courant, o)
            textes.append(courant)
    assert rejouer(d.journal, depart) == d.texte
    return d.version


if __name__ == "__main__":
    debut = time.time()
    test_scenario_classique()
    print("OK  scenario classique (suppression coupee, texte de Paul conserve)")
    test_meme_endroit_300_redacteurs()
    print("OK  300 redacteurs au meme endroit : aucune modification perdue")
    n = test_aleatoire()
    print(f"OK  5000 operations aleatoires avec redacteurs en retard ({n} versions)")
    print(f"duree : {time.time() - debut:.2f} s")
