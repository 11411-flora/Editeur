import os
import threading


class LiensMemoire:
    """Pour developper sur ton ordinateur. Le verrou fait passer une
    personne a la fois : verifier ET retirer ne font qu'un seul geste."""

    def __init__(self):
        self._liens = {}
        self._verrou = threading.Lock()

    def creer(self, lien_id, doc_id, createur, maximum):
        with self._verrou:
            self._liens[lien_id] = {
                "lien_id": lien_id, "doc_id": doc_id, "createur": createur,
                "maximum": maximum, "restants": maximum,
            }

    def lire(self, lien_id):
        with self._verrou:
            lien = self._liens.get(lien_id)
            return dict(lien) if lien else None

    def prendre(self, lien_id):
        """Retire un exemplaire. Renvoie ce qu'il en reste (0 pour le dernier),
        ou None si le lien est epuise ou inconnu."""
        with self._verrou:
            lien = self._liens.get(lien_id)
            if lien is None or lien["restants"] <= 0:
                return None
            lien["restants"] -= 1
            return lien["restants"]

    def lister(self):
        with self._verrou:
            return [dict(l) for l in self._liens.values()]


class LiensDynamo:
    """Pour le serveur AWS : utilise store.py."""

    def __init__(self):
        import store
        self.store = store

    def creer(self, lien_id, doc_id, createur, maximum):
        self.store.creer_lien_complet(lien_id, doc_id, createur, maximum)

    def lire(self, lien_id):
        return self.store.lire_lien(lien_id)

    def prendre(self, lien_id):
        return self.store.prendre_un_telechargement(lien_id)   # deja teste : 500 sur 1 000

    def lister(self):
        return self.store.lister_liens()


def creer():
    mode = os.environ.get("LIENS_BACKEND", "memoire")
    if mode == "dynamodb":
        return LiensDynamo()
    if mode == "memoire":
        return LiensMemoire()
    raise RuntimeError("LIENS_BACKEND doit valoir 'memoire' ou 'dynamodb'")
