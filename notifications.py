import threading
import time


class Notifications:
    """Boite d'envoi. Plus tard : un vrai envoi d'e-mail, via une file."""

    def __init__(self):
        self._envoyes = []
        self._verrou = threading.Lock()

    def dernier_telechargement(self, destinataire, lien_id, doc_id):
        with self._verrou:
            self._envoyes.append({
                "destinataire": destinataire,
                "lien_id": lien_id,
                "doc_id": doc_id,
                "sujet": "Votre lien de telechargement est epuise",
                "heure": time.time(),
            })
        print(f"[notification] dernier telechargement du lien {lien_id} -> {destinataire}")

    def liste(self):
        with self._verrou:
            return list(self._envoyes)


def creer():
    return Notifications()
