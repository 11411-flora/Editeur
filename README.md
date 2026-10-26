# Editeur
Projet_Stage_AWS
Projet d'évaluation : un petit éditeur de texte collaboratif pour le journal numérique d'une association. Plusieurs rédacteurs écrivent dans le même document en même temps, et on peut créer pour chaque document un lien qui permet de le télécharger en PDF un nombre limité de fois.

Projet individuel, réalisé en un week-end.

## Ce que fait l'application

- Un rédacteur entre avec un nom et une adresse e-mail (pas de compte).
- Il crée un document et donne accès à d'autres rédacteurs.
- Plusieurs personnes écrivent en même temps dans le même texte, et chacun voit les modifications des autres presque tout de suite, ainsi que les personnes présentes.
- On peut consulter les versions précédentes d'un document et en restaurer une.
- On peut créer un lien de téléchargement en PDF avec un nombre de téléchargements autorisé. Le lien donne toujours le document tel qu'il est au moment du clic.
- Chaque rédacteur dispose de 10 000 caractères d'écriture par jour. Au-delà, il ne peut plus écrire jusqu'au lendemain, et s'il insiste il est bloqué un moment.

## Les deux points sur lesquels j'ai le plus travaillé

**Nombre exact de téléchargements.** Le compteur d'un lien est retiré par une seule écriture conditionnelle dans DynamoDB (« retire 1 seulement s'il en reste »). Deux clics simultanés ne peuvent donc pas prendre le même dernier exemplaire.

**Aucune modification perdue.** Le texte n'est pas stocké tel quel : je stocke la liste des modifications, dans l'ordre. Le serveur donne un numéro à chaque modification et décale sa position si d'autres modifications sont passées avant elle (insertion contre insertion, insertion contre suppression, etc.). Tout le monde applique les mêmes modifications dans le même ordre et finit avec le même texte.

Le détail de ces choix est dans le dossier de conception.

## Organisation du dépôt

| Fichier ou dossier | Rôle |
| --- | --- |
| `server.py` | Le serveur : API HTTP, WebSocket, liens, crédit d'écriture |
| `doc.py` | Le document : journal des modifications et transformation des positions |
| `static/` | La page web (`index.html`, `client.js`, `ot.js`) |
| `test_*.py`, `test_*.js` | Les tests (voir plus bas) |
| `resultats_*.txt` | Les sorties brutes de mes tests |

## Lancer l'application en local

Il faut Python 3 version 3.10.12 et Node.js pour les tests du client.

```
git clone https://github.com/11411-flora/Editeur.git
cd Editeur
pip install -r requirements.txt  
python3 server.py                  
```

Puis ouvrir `http://localhost:[port]` dans le navigateur. Pour essayer l'écriture à plusieurs, ouvrir le même document dans deux fenêtres.

## Lancer les tests

```
python3 test_collaboration.py
python3 test_ws.py
python3 test_regression_http.py
node test_ot_js.js
node test_client_js.js
node test_page_jsdom.js
node test_e2e_node.js
```

Les tests de collaboration envoient des modifications simultanées au même endroit et vérifient que le texte final est identique partout et qu'aucune insertion n'a disparu. Les résultats que j'ai obtenus sont dans les fichiers `resultats_*.txt` et analysés dans le rapport de test.

## Déploiement sur AWS

Incident de déploiement sur AWS. Au premier démarrage sur l’instance, le service redémarrait en boucle puis systemd l’abandonnait (« start-limit-hit »). Deux causes successives. D’abord, reportlab refusait de s’importer parce que la version de Python du système était inférieure à 3.10 ; j’ai utilisé un environnement virtuel avec une version suffisante. Ensuite, le service lançait python3 server.py, qui chargeait le fichier puis se terminait sans démarrer de serveur. J’ai remplacé la commande par uvicorn server:app --host 127.0.0.1 --port 8000. Après correction, le service est resté actif sans redémarrage et répond 200 sur le port 8000, puis sur le port 80 via nginx. Je garde cet incident dans le rapport parce qu’il montre que le déploiement a été vérifié et pas seulement supposé.

Aucune clé d'accès AWS n'est dans le code ni dans le dépôt : le serveur utilise le rôle IAM de l'instance.

## Limites

- Un seul processus d'écriture, pour garder un seul ordre des modifications. S'il tombe, l'édition s'arrête jusqu'au redémarrage, mais rien n'est perdu puisque le journal est dans la base.
- Texte brut uniquement, sans mise en forme.
- Identification par e-mail sans mot de passe, comme le permet le sujet.
