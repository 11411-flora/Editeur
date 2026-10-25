import os
import threading
import time


class Blocage:
    """Compte les refus de credit de chaque redacteur.
    Trop de refus en peu de temps : il est bloque pour un moment."""

    def __init__(self, seuil=5, fenetre=60, duree=600, horloge=time.time):
        self.seuil = seuil          # nombre de refus qui declenche le blocage
        self.fenetre = fenetre      # en secondes : on ne compte que les refus recents
        self.duree = duree          # en secondes : duree du blocage
        self.horloge = horloge      # modifiable, pour tester sans attendre
        self._refus = {}            # email -> heures des refus recents
        self._jusqua = {}           # email -> heure de fin de blocage
        self._verrou = threading.Lock()

    def reste(self, email):
        """Secondes de blocage restantes (0 si pas bloque)."""
        email = email.lower()
        with self._verrou:
            fin = self._jusqua.get(email, 0)
            maintenant = self.horloge()
            if fin > maintenant:
                return fin - maintenant
            self._jusqua.pop(email, None)
            return 0

    def enregistrer_refus(self, email):
        """A appeler a chaque refus de credit. Renvoie True si CE refus
        declenche le blocage."""
        email = email.lower()
        with self._verrou:
            maintenant = self.horloge()
            recents = [t for t in self._refus.get(email, []) if maintenant - t < self.fenetre]
            recents.append(maintenant)
            if len(recents) >= self.seuil:
                self._jusqua[email] = maintenant + self.duree
                self._refus.pop(email, None)
                return True
            self._refus[email] = recents
            return False

    def liste(self):
        """Les personnes bloquees en ce moment, avec le temps restant."""
        with self._verrou:
            maintenant = self.horloge()
            return {e: int(fin - maintenant) for e, fin in self._jusqua.items() if fin > maintenant}


def creer():
    return Blocage(
        seuil=int(os.environ.get("BLOCAGE_SEUIL", "5")),
        fenetre=int(os.environ.get("BLOCAGE_FENETRE_S", "60")),
        duree=int(os.environ.get("BLOCAGE_DUREE_S", "600")),
    )
