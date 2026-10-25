from blocage import Blocage


class Horloge:
    def __init__(self):
        self.t = 1000.0
    def __call__(self):
        return self.t


def test_cinq_refus_bloquent():
    h = Horloge()
    b = Blocage(seuil=5, fenetre=60, duree=600, horloge=h)
    for i in range(4):
        assert b.enregistrer_refus("a@x.fr") is False
        h.t += 1
    assert b.reste("a@x.fr") == 0                     # pas encore bloque
    assert b.enregistrer_refus("a@x.fr") is True       # le 5e declenche
    assert 590 < b.reste("a@x.fr") <= 600


def test_deblocage_apres_la_duree():
    h = Horloge()
    b = Blocage(seuil=2, fenetre=60, duree=600, horloge=h)
    b.enregistrer_refus("a@x.fr")
    assert b.enregistrer_refus("a@x.fr") is True
    h.t += 599
    assert b.reste("a@x.fr") > 0
    h.t += 2
    assert b.reste("a@x.fr") == 0                      # redevenu libre


def test_refus_espaces_ne_bloquent_pas():
    h = Horloge()
    b = Blocage(seuil=5, fenetre=60, duree=600, horloge=h)
    for _ in range(20):
        assert b.enregistrer_refus("a@x.fr") is False  # un refus toutes les 61 s
        h.t += 61


def test_un_autre_redacteur_nest_pas_touche():
    h = Horloge()
    b = Blocage(seuil=2, fenetre=60, duree=600, horloge=h)
    b.enregistrer_refus("a@x.fr")
    b.enregistrer_refus("a@x.fr")
    assert b.reste("a@x.fr") > 0
    assert b.reste("b@x.fr") == 0
    assert list(b.liste()) == ["a@x.fr"]


def test_majuscules_meme_personne():
    h = Horloge()
    b = Blocage(seuil=2, fenetre=60, duree=600, horloge=h)
    b.enregistrer_refus("A@X.fr")
    assert b.enregistrer_refus("a@x.fr") is True


if __name__ == "__main__":
    test_cinq_refus_bloquent()
    print("OK  5 refus en moins de 60 s : bloque 10 minutes")
    test_deblocage_apres_la_duree()
    print("OK  apres la duree, le redacteur est libre")
    test_refus_espaces_ne_bloquent_pas()
    print("OK  des refus espaces ne bloquent personne")
    test_un_autre_redacteur_nest_pas_touche()
    print("OK  un autre redacteur n'est pas touche")
    test_majuscules_meme_personne()
    print("OK  A@x.fr et a@x.fr sont la meme personne")
