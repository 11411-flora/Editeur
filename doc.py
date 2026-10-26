import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class Op:
    kind: str
    pos: int
    text: str = ""
    length: int = 0


def ins(pos, text):
    return Op("ins", pos, text=text)


def dele(pos, length):
    return Op("del", pos, length=length)


def appliquer(texte, op):
    if op.kind == "ins":
        return texte[:op.pos] + op.text + texte[op.pos:]
    return texte[:op.pos] + texte[op.pos + op.length:]


def transformer(op, autre, autre_gagne=True):
    if op.kind == "ins":
        if autre.kind == "ins":
            decale = autre.pos <= op.pos if autre_gagne else autre.pos < op.pos
            p = op.pos + len(autre.text) if decale else op.pos
            return [ins(p, op.text)]
        a, n = autre.pos, autre.length
        if op.pos <= a:
            p = op.pos
        elif op.pos >= a + n:
            p = op.pos - n
        else:
            p = a
        return [ins(p, op.text)]

    if autre.kind == "ins":
        q, u = autre.pos, len(autre.text)
        if q <= op.pos:
            return [dele(op.pos + u, op.length)]
        if q >= op.pos + op.length:
            return [op]
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


def croiser(a, b):
    """a et b : deux listes d'operations ecrites sur le MEME texte (chaque liste
    est une suite : la 2e operation suppose la 1re deja faite).
    "a" est passee en premier et gagne les egalites.
    Renvoie (a2, b2) avec :  b puis a2  ==  a puis b2."""
    if not a or not b:
        return a, b
    if len(a) > 1:
        a1, b1 = croiser(a[:1], b)
        a2, b2 = croiser(a[1:], b1)
        return a1 + a2, b2
    if len(b) > 1:
        a1, b1 = croiser(a, b[:1])
        a2, b2 = croiser(a1, b[1:])
        return a2, b1 + b2
    x, y = a[0], b[0]
    return transformer(x, y, False), transformer(y, x, True)


class Document:
    def __init__(self, texte=""):
        self.texte = texte
        self._depart = texte          # texte de depart : sert a rejouer l'historique
        self.journal = []
        self._verrou = threading.Lock()

    @property
    def version(self):
        return len(self.journal)

    def soumettre(self, op, version_de_base):
        with self._verrou:
            if not 0 <= version_de_base <= len(self.journal):
                raise ValueError("version inconnue")
            ops = [op]
            for deja in self.journal[version_de_base:]:
                # deja est passee avant nous : elle gagne les egalites
                _, ops = croiser([deja], ops)
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

    def instantane(self):
        with self._verrou:
            return self.texte, len(self.journal)

    def journal_depuis(self, version):
        with self._verrou:
            return list(self.journal[version:]), len(self.journal)

    def texte_a(self, version):
        """Le texte tel qu'il etait a une version donnee (0 = document vide)."""
        with self._verrou:
            if not 0 <= version <= len(self.journal):
                raise ValueError("version inconnue")
            t = self._depart
            for o in self.journal[:version]:
                t = appliquer(t, o)
            return t

    def restaurer(self, version):
        """Remet le texte d'une version ancienne en ajoutant de NOUVELLES operations
        au journal : l'historique n'est jamais reecrit."""
        with self._verrou:
            if not 0 <= version <= len(self.journal):
                raise ValueError("version inconnue")
            ancien = self._depart
            for o in self.journal[:version]:
                ancien = appliquer(ancien, o)
            ops = []
            if self.texte:
                ops.append(dele(0, len(self.texte)))
            if ancien:
                ops.append(ins(0, ancien))
            for o in ops:
                self.texte = appliquer(self.texte, o)
            self.journal.extend(ops)
            return ops, len(self.journal), ancien
