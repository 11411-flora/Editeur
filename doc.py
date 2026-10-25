import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class Op:
    kind: str          # "ins" (inserer) ou "del" (supprimer)
    pos: int
    text: str = ""     # pour "ins"
    length: int = 0    # pour "del"


def ins(pos, text):
    return Op("ins", pos, text=text)


def dele(pos, length):
    return Op("del", pos, length=length)


def appliquer(texte, op):
    if op.kind == "ins":
        return texte[:op.pos] + op.text + texte[op.pos:]
    return texte[:op.pos] + texte[op.pos + op.length:]


def transformer(op, autre):
    """op et autre ont ete ecrites sur le MEME texte, et autre est deja
    appliquee. Renvoie la liste d'operations equivalentes a op, valables
    APRES autre."""
    if op.kind == "ins":
        if autre.kind == "ins":
            # meme position : celui arrive en premier passe devant
            p = op.pos + len(autre.text) if autre.pos <= op.pos else op.pos
            return [ins(p, op.text)]
        a, n = autre.pos, autre.length
        if op.pos <= a:
            p = op.pos
        elif op.pos >= a + n:
            p = op.pos - n
        else:
            p = a            # on inserait dans une zone supprimee
        return [ins(p, op.text)]

    # op est une suppression
    if autre.kind == "ins":
        q, u = autre.pos, len(autre.text)
        if q <= op.pos:
            return [dele(op.pos + u, op.length)]
        if q >= op.pos + op.length:
            return [op]
        # insertion au milieu de la zone : on coupe en deux pour
        # ne PAS supprimer le texte de l'autre
        gauche = q - op.pos
        return [dele(op.pos, gauche),
                dele(op.pos + u, op.length - gauche)]

    p, n = op.pos, op.length
    q, m = autre.pos, autre.length
    chevauchement = max(0, min(p + n, q + m) - max(p, q))
    reste = n - chevauchement
    if reste == 0:
        return []
    if q + m <= p:
        nouvelle = p - m
    elif q >= p + n:
        nouvelle = p
    else:
        nouvelle = min(p, q)
    return [dele(nouvelle, reste)]


class Document:
    def __init__(self, texte=""):
        self.texte = texte
        self.journal = []                 # la version = len(journal)
        self._verrou = threading.Lock()   # un seul guichet

    @property
    def version(self):
        return len(self.journal)

    def soumettre(self, op, version_de_base):
        """op a ete ecrite par un rediacteur qui voyait la version
        version_de_base. Renvoie (operations_acceptees, nouvelle_version)."""
        with self._verrou:
            if not 0 <= version_de_base <= len(self.journal):
                raise ValueError("version inconnue")
            ops = [op]
            for deja in self.journal[version_de_base:]:
                suite = []
                for o in ops:
                    suite.extend(transformer(o, deja))
                ops = suite
            texte = self.texte
            for o in ops:
                self._verifier(o, texte)
                texte = appliquer(texte, o)
            self.texte = texte
            self.journal.extend(ops)
            return ops, len(self.journal)

    @staticmethod
    def _verifier(op, texte):
        if op.kind == "ins":
            ok = op.text != "" and 0 <= op.pos <= len(texte)
        else:
            ok = op.length > 0 and 0 <= op.pos and op.pos + op.length <= len(texte)
        if not ok:
            raise ValueError(f"operation invalide : {op}")
