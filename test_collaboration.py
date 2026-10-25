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
    d = Document("ABCDEF")
    d.soumettre(dele(2, 2), 0)
    d.soumettre(ins(3, "X"), 0)
    assert d.texte == "ABXEF", d.texte
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
        barriere.wait()
        d.soumettre(ins(0, jeton), 0)

    fils = [threading.Thread(target=redacteur, args=(j,)) for j in jetons]
    for f in fils:
        f.start()
    for f in fils:
        f.join()

    perdus = [j for j in jetons if j not in d.texte]
    assert not perdus, f"modifications perdues : {perdus[:5]}"
    assert len(d.texte) == 5 * n
    assert d.version == n
    assert rejouer(d.journal) == d.texte


def test_aleatoire(n_ops=5000, graine=1):
    rnd = random.Random(graine)
    depart = "0123456789"
    d = Document(depart)
    textes = [depart]
    for _ in range(n_ops):
        v = rnd.randint(max(0, d.version - 5), d.version)
        t = textes[v]
        if rnd.random() < 0.6 or not t:
            op = ins(rnd.randint(0, len(t)),
                     rnd.choice("abcdefgh") * rnd.randint(1, 3))
        else:
            p = rnd.randint(0, len(t) - 1)
            op = dele(p, rnd.randint(1, min(4, len(t) - p)))
        d.soumettre(op, v)
        courant = textes[-1]
        for o in d.journal[len(textes) - 1:]:
            courant = appliquer(courant, o)
            textes.append(courant)
    assert rejouer(d.journal, depart) == d.texte
    return d.version


def test_suppressions_coupees_puis_croisees():
    """Cas qui cassait avant : une suppression coupee en deux (par une insertion),
    puis une autre operation concurrente. Chaque morceau depend du precedent."""
    d = Document("0123456789")
    d.soumettre(ins(7, "X"), 0)        # insere au milieu de la zone que 'A' va supprimer
    d.soumettre(dele(5, 3), 0)         # coupee en deux : [del(5,2), del(6,1)] apres decalage
    d.soumettre(dele(6, 2), 0)         # recoupe les memes caracteres
    # les chiffres supprimes ont disparu, le X de l'autre redacteur a survecu
    assert "X" in d.texte
    assert all(c not in d.texte for c in "567"), d.texte


if __name__ == "__main__":
    debut = time.time()
    test_scenario_classique()
    print("OK  scenario classique (suppression coupee, texte de Paul conserve)")
    test_meme_endroit_300_redacteurs()
    print("OK  300 redacteurs au meme endroit : aucune modification perdue")
    n = test_aleatoire()
    print(f"OK  5000 operations aleatoires avec redacteurs en retard ({n} versions)")
    test_suppressions_coupees_puis_croisees()
    print("OK  suppressions coupees puis croisees avec d'autres modifications")
    print(f"duree : {time.time() - debut:.2f} s")
