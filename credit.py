import os
import threading
from datetime import datetime, timezone

LIMITE_JOUR = 10_000


def jour_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class CreditMemoire:
    """Version pour developper sur ton ordinateur. Le verrou fait passer
    une personne a la fois : verifier et retirer ne font qu'un seul geste."""

    def __init__(self, limite=LIMITE_JOUR):
        self.limite = limite
        self._utilises = {}
        self._verrou = threading.Lock()

    def consommer(self, email, n, jour=None):
        """Renvoie le total utilise apres l'operation, ou None si refuse."""
        if n <= 0:
            raise ValueError("n doit etre positif")
        cle = (email.lower(), jour or jour_utc())
        with self._verrou:
            deja = self._utilises.get(cle, 0)
            if deja + n > self.limite:
                return None
            self._utilises[cle] = deja + n
            return deja + n

    def rembourser(self, email, n, jour=None):
        cle = (email.lower(), jour or jour_utc())
        with self._verrou:
            self._utilises[cle] = max(0, self._utilises.get(cle, 0) - n)

    def utilises(self, email, jour=None):
        cle = (email.lower(), jour or jour_utc())
        with self._verrou:
            return self._utilises.get(cle, 0)


class CreditDynamo:
    """Version pour le serveur AWS : utilise store.py (deja teste)."""

    def __init__(self):
        import store   # import tardif : il faut boto3 et une region
        self.store = store
        self.limite = store.LIMITE_JOUR

    def consommer(self, email, n, jour=None):
        return self.store.consommer_credit(email, n, jour)

    def rembourser(self, email, n, jour=None):
        self.store.rembourser_credit(email, n, jour)

    def utilises(self, email, jour=None):
        return self.store.lire_credit(email, jour)


def creer():
    mode = os.environ.get("CREDIT_BACKEND", "memoire")
    if mode == "dynamodb":
        return CreditDynamo()
    if mode == "memoire":
        return CreditMemoire()
    raise RuntimeError("CREDIT_BACKEND doit valoir 'memoire' ou 'dynamodb'")
