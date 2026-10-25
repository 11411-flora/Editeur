import random
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import store

email = f"test-{uuid.uuid4().hex[:8]}@exemple.fr"
random.seed(7)
tailles = [random.randint(1, 300) for _ in range(300)]   # ~45 000 caracteres demandes


def ecrire(n):
    # 20 fils en parallele = un redacteur qui ecrit depuis 20 appareils
    return n if store.consommer_credit(email, n) is not None else 0


debut = time.time()
with ThreadPoolExecutor(max_workers=20) as pool:
    acceptes = list(pool.map(ecrire, tailles))
duree = time.time() - debut

total_accepte = sum(acceptes)
en_base = store.lire_credit(email)
print(f"caracteres demandes    : {sum(tailles)}")
print(f"caracteres acceptes    : {total_accepte}")
print(f"utilises en base       : {en_base}")
print(f"duree                  : {duree:.1f} s")
assert en_base <= store.LIMITE_JOUR, "credit depasse !"
assert total_accepte == en_base, "ecart entre acceptes et base !"
print("OK  jamais plus que 10 000, et la base correspond a ce qui a ete accepte")

# le credit peut etre epuise exactement, puis plus rien ne passe
reste = store.LIMITE_JOUR - en_base
if reste > 0:
    assert store.consommer_credit(email, reste) == store.LIMITE_JOUR
assert store.consommer_credit(email, 1) is None
print("OK  credit epuise exactement, puis refus")

# le lendemain, une fiche vierge
assert store.consommer_credit(email, 100, jour="2000-01-02") == 100
print("OK  recharge : un autre jour repart de zero")
