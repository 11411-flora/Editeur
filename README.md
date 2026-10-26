# Éditeur de documents partagé

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

**Nombre exact de téléchargements.** Le compteur d'un lien est retiré par une seule écriture conditionnelle (« retire 1 seulement s'il en reste »). Deux clics simultanés ne peuvent donc pas prendre le même dernier exemplaire.

**Aucune modification perdue.** Le texte n'est pas stocké tel quel : je stocke la liste des modifications, dans l'ordre. Le serveur donne un numéro à chaque modification et décale sa position si d'autres modifications sont passées avant elle (insertion contre insertion, insertion contre suppression, etc.). Tout le monde applique les mêmes modifications dans le même ordre et finit avec le même texte.

Le détail de ces choix est dans le dossier de conception.

## Organisation du dépôt

| Fichier ou dossier | Rôle |
| --- | --- |
| `server.py` | Le serveur : API HTTP, WebSocket, liens, crédit d'écriture |
| `doc.py` | Le document : journal des modifications et transformation des positions |
| `static/` | La page web (`index.html`, `client.js`, `ot.js`) |
| `infra/` | Description de l'infrastructure : service systemd et configuration nginx |
| `test_*.py`, `test_*.js` | Les tests (voir plus bas) |
| `resultats_*.txt` | Les sorties brutes de mes tests, en local et sur AWS |
| `requirements.txt` | Les dépendances Python |

## Infrastructure

Tout est dans une seule région AWS, **eu-north-1 (Stockholm)**, en plan gratuit.

```
Navigateur  →  nginx (port 80)  →  uvicorn (127.0.0.1:8000)  →  server.py
                                         instance EC2, Amazon Linux 2023
```

| Ressource | Rôle | Description dans le dépôt |
| --- | --- | --- |
| Instance EC2 | Fait tourner l'application | ce README |
| Groupe de sécurité | Port 80 ouvert à tous, port 22 limité à mon adresse IP | ce README |
| Service systemd `editeur` | Lance et relance le serveur | `infra/editeur.service` |
| nginx | Reçoit le port 80, transmet à uvicorn, laisse passer les WebSocket | `infra/nginx-editeur.conf` |

Le serveur d'écriture est volontairement un **seul processus** : c'est lui qui fixe l'ordre des modifications. Ne pas lancer uvicorn avec `--workers`.

Aucune clé d'accès AWS n'est dans le code ni dans le dépôt. Les seuls secrets sont dans `/etc/editeur.env` sur l'instance (jeton d'administration), jamais dans Git.

## Lancer l'application en local

Il faut Python 3.10 ou plus (la bibliothèque `reportlab` l'exige) et Node.js pour les tests du client.

```
git clone https://github.com/11411-flora/Editeur.git
cd Editeur
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --host 127.0.0.1 --port 8000
```

Puis ouvrir `http://localhost:8000` dans le navigateur. Pour essayer l'écriture à plusieurs, ouvrir le même document dans deux fenêtres, avec deux identités différentes.

Attention : `python3 server.py` ne démarre pas le serveur, il faut passer par `uvicorn`. `requirements.txt` doit contenir `websockets`, sinon la connexion en direct est refusée.

## Déployer sur AWS

Prérequis : un compte AWS, une paire de clés SSH, et l'AWS CLI configurée sur mon ordinateur (`aws configure`). Les identifiants restent dans `~/.aws/`, jamais dans le dépôt.

### 1. Créer l'instance

Dans la console AWS, région eu-north-1 :

1. Lancer une instance EC2 du plan gratuit, image **Amazon Linux 2023**, avec ma paire de clés.
2. Groupe de sécurité : entrée **HTTP (80)** depuis partout, entrée **SSH (22)** depuis mon adresse IP uniquement. Ne pas ouvrir le port 8000.
3. Noter l'adresse IP publique. Elle change à chaque arrêt de l'instance, sauf avec une IP élastique.

### 2. Envoyer le code

Depuis mon ordinateur, dans le dossier parent du dépôt :

```
tar czf editeur_deploy.tgz --exclude=.venv --exclude=__pycache__ --exclude=pdf_cache --exclude=.git Editeur
scp -i ma_cle.pem editeur_deploy.tgz ec2-user@ADRESSE_IP:/tmp/
ssh -i ma_cle.pem ec2-user@ADRESSE_IP
```

### 3. Installer sur l'instance

```
sudo dnf install -y nginx python3.11
sudo useradd --system editeur
sudo mkdir -p /opt/editeur
sudo tar xzf /tmp/editeur_deploy.tgz -C /opt/editeur --strip-components=1
sudo python3.11 -m venv /opt/editeur/.venv
sudo /opt/editeur/.venv/bin/pip install -r /opt/editeur/requirements.txt
sudo chown -R editeur:editeur /opt/editeur
```

Le jeton d'administration se crée une seule fois (la commande ne fait rien s'il existe déjà) :

```
sudo sh -c 'grep -q "^ADMIN_TOKEN=" /etc/editeur.env 2>/dev/null || echo "ADMIN_TOKEN=$(openssl rand -hex 16)" >> /etc/editeur.env'
sudo chmod 600 /etc/editeur.env
```

### 4. Démarrer le service et nginx

```
sudo cp /opt/editeur/infra/editeur.service /etc/systemd/system/editeur.service
sudo cp /opt/editeur/infra/nginx-editeur.conf /etc/nginx/conf.d/editeur.conf
sudo systemctl daemon-reload
sudo systemctl enable --now editeur
sudo nginx -t && sudo systemctl enable --now nginx
```

Si `nginx -t` signale un conflit sur `server_name "_"`, la configuration par défaut de nginx répond à la place de l'application : changer son `server_name` dans `/etc/nginx/nginx.conf`.

### 5. Vérifier

```
sudo systemctl status editeur --no-pager
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1/
```

Les deux `curl` doivent afficher `200` et le service doit rester `active (running)`. Ouvrir ensuite `http://ADRESSE_IP/` dans un navigateur : si la page affiche « Connexion perdue », la bibliothèque `websockets` manque (`sudo journalctl -u editeur -n 30`).

Pour redéployer une nouvelle version : refaire les étapes 2 et 3 (extraction et `pip install`), puis `sudo systemctl restart editeur`.

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

Pour tester l'instance AWS plutôt que mon ordinateur, changer l'adresse cible en tête des scripts par `http://ADRESSE_IP`.

- `test_collaboration.py` et `test_ws.py` envoient des modifications simultanées au même endroit et vérifient que le texte final est identique partout et qu'aucune insertion n'a disparu.
- `test_regression_http.py` vérifie que l'API HTTP répond toujours comme prévu.
- Les scripts `.js` testent la transformation des positions dans le navigateur, la page et un parcours complet.

Les sorties sont enregistrées dans les fichiers `resultats_*.txt` (suffixe `_aws` pour l'instance), et analysées dans le rapport de test.

## Tout supprimer

À faire une fois le projet rendu, pour ne rien laisser tourner ni facturer. Région eu-north-1. Les identifiants viennent de l'AWS CLI.

```
export AWS_REGION=eu-north-1

# L'instance, puis le groupe de sécurité et la paire de clés
aws ec2 terminate-instances --instance-ids i-XXXXXXXX
aws ec2 wait instance-terminated --instance-ids i-XXXXXXXX
aws ec2 delete-security-group --group-id sg-XXXXXXXX
aws ec2 delete-key-pair --key-name NOM_DE_LA_CLE

# Si une IP élastique a été créée
aws ec2 release-address --allocation-id eipalloc-XXXXXXXX
```

Vérifier qu'il ne reste rien :

```
aws ec2 describe-instances --filters Name=instance-state-name,Values=running --query "Reservations[].Instances[].InstanceId"
```

La liste doit être vide. Contrôler aussi la page de facturation de la console AWS le lendemain.

Sur mon ordinateur : supprimer le dossier du dépôt et la clé `.pem`, et révoquer le jeton GitHub s'il a été créé pour ce projet.

## Limites

- Un seul processus d'écriture, pour garder un seul ordre des modifications. S'il tombe, l'édition s'arrête jusqu'au redémarrage, mais rien n'est perdu puisque le journal est conservé.
- Texte brut uniquement, sans mise en forme.
- Identification par e-mail sans mot de passe, comme le permet le sujet.
- Trafic en HTTP, sans nom de domaine ni certificat.
