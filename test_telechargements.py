import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import store

N_LIEN = 500          # telechargements autorises
N_VISITEURS = 1000    # clics simultanes
N_THREADS = 50        # visiteurs "en meme temps"

mode = sys.argv[1] if len(sys.argv) > 1 else "atomique"
fonction = (
    store.prendre_un_telechargement
    if mode == "atomique"
    else store.prendre_un_telechargement_naif
)

lien_id = "test-" + uuid.uuid4().hex[:8]
store.creer_lien(lien_id, N_LIEN)


def visiteur(_):
    # Attention : le dernier exemplaire renvoie 0, donc on teste "is not None"
    return fonction(lien_id) is not None


debut = time.time()
with ThreadPoolExecutor(max_workers=N_THREADS) as pool:
    resultats = list(pool.map(visiteur, range(N_VISITEURS)))
duree = time.time() - debut

reussites = sum(resultats)
print(f"mode                   : {mode}")
print(f"lien                   : {lien_id}")
print(f"autorises a la creation: {N_LIEN}")
print(f"visiteurs              : {N_VISITEURS}")
print(f"telechargements donnes : {reussites}")
print(f"refus ('epuise')       : {N_VISITEURS - reussites}")
print(f"restants en base       : {store.lire_restants(lien_id)}")
print(f"duree                  : {duree:.1f} s")
print("VERDICT                :", "OK" if reussites == N_LIEN else "ECHEC")
