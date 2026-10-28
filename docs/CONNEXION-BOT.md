# Raccorder le site au bot existant

Le site parle à Discord avec le jeton de ton bot, sans démarrer un deuxième bot.
Le backend du site doit tourner sur le PC Linux (ou un autre hôte Python).
GitHub Pages ne lit jamais le fichier `.env` et n’exécute pas Python.

Installation Linux communiquée :

- Système : Ubuntu 26.04 LTS, sur un PC distinct du poste Windows de développement.
- Service existant : `blanchimentbot.service`.
- Programme du bot : `/home/dojojo/Documents/bot_blanchiment/bot.py`.
- Aucun nom de domaine pour le moment.

Le dossier du site est à installer séparément du dossier du bot. Ne pas remplacer
le programme ou le service du bot par les scripts de lancement du site.
Pour les premiers essais, un Quick Tunnel Cloudflare peut fournir une adresse
HTTPS temporaire sans domaine. L’adresse change à chaque redémarrage du tunnel :
il faut alors actualiser la configuration du site et le retour OAuth2 Discord.
Ce tunnel de test ne constitue pas une adresse de production permanente.

## 1. Configuration privée du site

Copier `.env.example` vers `.env` seulement si `.env` n’existe pas déjà.
Renseigner dans `.env`, sans publier ce fichier :

| Variable | Valeur |
| --- | --- |
| `DISCORD_CLIENT_ID` | Application ID de l’application de ton bot |
| `DISCORD_CLIENT_SECRET` | Client Secret OAuth2 de cette application |
| `DISCORD_BOT_TOKEN` | Jeton du bot existant, distinct du Client Secret |
| `DISCORD_GUILD_ID` | ID de ton serveur Discord |
| `HERITAGE_SUPREME_ID` | Ton ID utilisateur Discord |
| `HERITAGE_EMPLOYEE_ROLE_ID` | ID du rôle donnant accès au site |
| `HERITAGE_BASE_URL` | Origine du site Python : `http://127.0.0.1:8081` en local, ou son adresse HTTPS publique |
| `HERITAGE_LOCAL_PREVIEW` | `0` pour la vraie connexion Discord |
| `HERITAGE_SEED_DEMO_DATA` | `0` pour démarrer une base métier neuve vide, sans dossiers fictifs |
| `HERITAGE_CONNECTOR_SECRET` | Secret aléatoire d’au moins 32 caractères, partagé uniquement entre le site et le bot |
| `HERITAGE_BOT_COMMANDS_ENABLED` | Garder `0` jusqu’à l’installation du gestionnaire d’opérations dans le bot |

Générer un secret dans ton terminal privé :

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Sur le PC Linux, depuis le dossier du site :

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/check_discord.py
.venv/bin/python scripts/serve.py
```

Le contrôle vérifie en lecture seule le jeton, l’accès au serveur et le rôle
Employé. Le Client Secret est réellement validé pendant la connexion OAuth2.
Dans le portail développeur Discord, ajouter exactement le retour affiché par
le contrôle, par exemple `http://127.0.0.1:8081/auth/callback` pour un essai local.
Ouvrir alors `http://127.0.0.1:8081/` et se connecter avec Discord : les grades
du serveur apparaissent dans Gestion → Accès, pour ton compte propriétaire.

Les anciennes données d’essai du navigateur ne sont pas importées dans la base
du serveur. Une base SQLite déjà présente n’est pas effacée automatiquement.

## 2. Relier l’entrée GitHub Pages

Pour les visiteurs extérieurs, le backend doit avoir une vraie adresse HTTPS
accessible depuis Internet. Ce point nécessite un domaine/tunnel/proxy à configurer
sur le PC Linux ; le code ne peut pas créer cette adresse automatiquement.

Renseigner la même origine dans les deux variables :

```dotenv
HERITAGE_BASE_URL=https://ton-site.example
HERITAGE_PUBLIC_BACKEND_URL=https://ton-site.example
```

Remplacer l’exemple par ta vraie adresse, puis lancer :

```bash
.venv/bin/python scripts/configure_connection.py
```

Pour changer d’adresse de tunnel sans modifier les secrets, on peut aussi lancer
`scripts/configure_connection.py --url https://ADRESSE-DU-TUNNEL` avec le Python
du site. Cette commande met à jour les deux adresses dans le `.env` privé et
génère le JSON public. Utiliser ensuite la même origine dans le retour OAuth2.
Après un changement du `.env`, arrêter puis relancer uniquement le Python du site.
Le processus Cloudflare doit rester ouvert pour conserver la même adresse.

Si l’adresse publique renvoie `400 Invalid host header`, le backend en cours
d’exécution n’accepte pas ce nom de tunnel : vérifier `HERITAGE_BASE_URL` dans
le `.env` du PC Linux, puis redémarrer le Python. Ne pas supprimer le contrôle
des hôtes et ne pas remplacer la liste des hôtes autorisés par `*`.

Publier `static/site-config.json` avec les fichiers du site sur GitHub. Ce fichier
contient uniquement l’adresse publique du backend. L’accueil GitHub affiche
« Se connecter avec Discord » ; le clic ouvre `/auth/start` sur le backend.
Il n’y a pas de redirection automatique à l’ouverture de l’accueil.
La connexion et les sessions restent sur la même origine,
sans jeton dans JavaScript ni cookies tiers entre GitHub et le PC Linux.
Ajouter aussi `https://ton-site.example/auth/callback` aux retours OAuth2 Discord.
Laisser `HERITAGE_PUBLIC_BACKEND_URL` vide et régénérer le JSON désactive le bouton
de connexion, sans accorder d’accès aux pages privées. Pour lancer volontairement
les anciens essais locaux, utiliser `scripts/configure_connection.py --preview`.
Ce mode est explicite et indépendant des vrais comptes et données.

## 3. Échanges entre le programme du bot et le site

Copier `connectors/website_client.py` dans le projet du bot existant.
Il n’instancie aucun client Discord et ne remplace pas ton bot.
Dans la configuration privée du bot :

```dotenv
HERITAGE_SITE_URL=http://127.0.0.1:8081
HERITAGE_CONNECTOR_SECRET=LE_MEME_SECRET_QUE_DANS_LE_SITE
DISCORD_GUILD_ID=ID_DU_SERVEUR_DISCORD
```

Le bot peut utiliser HTTP loopback si les deux programmes tournent sur le même
PC Linux. Depuis une autre machine, utiliser l’adresse HTTPS du site.
Les variables doivent être chargées dans l’environnement du bot par son lancement
habituel ou son chargeur `.env`.

```python
from website_client import WebsiteClient

website = WebsiteClient.from_env()

# À appeler dans le bot existant, après sa connexion :
await website.event('ready')

# À intégrer dans les écouteurs du bot, en vérifiant le serveur concerné :
await website.event('member_update', userId=str(member.id))
await website.event('member_remove', userId=str(member.id))
await website.event('roles_update')
```

Avec discord.py, les événements des membres nécessitent l’intent Members côté
code et dans le portail Discord. Les contrôles REST du site fonctionnent aussi
sans ces notifications ; les notifications accélèrent l’invalidation des accès.
Ne pas remplacer les écouteurs existants : ajouter ces appels aux bons endroits.
Les erreurs réseau du site doivent être capturées et journalisées par le bot,
sans interrompre ses commandes Discord.

## 4. Opérations métier : le raccordement à adapter dans ton bot

Mettre des IDs et des jetons dans `.env` ne dit pas au bot comment modifier ses
propres dossiers, tableaux et messages. Ce dernier raccordement utilise ses
fonctions existantes, qui ne sont pas présentes dans ce dossier.

Le transport est prêt dans les deux sens :

- Site → bot : les opérations validées sont mises en file durable si
  `HERITAGE_BOT_COMMANDS_ENABLED=1`. Elles restent en attente jusqu’à confirmation.
- Bot → site : envoyer un événement `action` avec un identifiant stable. Les
  doublons ne réappliquent pas l’opération et ne repartent pas dans la file du bot.

Exemple d’opération issue du bot :

```python
result = await website.event(
    'action',
    event_id='discord-message-' + str(message.id),
    page='tombola', action='raffle-record',
    actor={'id': str(member.id), 'name': member.display_name},
    values={'vehicle0': 'Brioso', 'type0': 'voiture', 'price0': '125000',
            'vehicle1': 'Bati 801', 'type1': 'moto', 'price1': ''},
)
site_record_id = result['recordId']
```

Conserver `site_record_id` dans le stockage du bot pour les modifications futures
(`recordId`). Réutiliser le même `event_id` lors d’une relance du même événement ;
utiliser un nouvel ID pour une nouvelle modification.

Les pages/actions autorisées sont définies dans `backend/domain.py`, dans `ACTIONS`.
Les champs `values` sont ceux des formulaires du site ; ils restent validés côté Python.

Pour lire les actions faites sur le site :

```python
async def handle_site_command(command):
    # À implémenter avec les fonctions de TON bot.
    # command['id'] doit être dédupliqué durablement dans le stockage du bot.
    # command['body'] contient page, action, values, actor et le dossier résultant.
    # Mapper aussi les IDs des dossiers du site aux IDs du bot.
    raise NotImplementedError('Brancher ici les opérations du bot existant')

# Créer une seule tâche après démarrage du bot, pas à chaque reconnexion.
# website.poll confirme une action seulement si le gestionnaire réussit.
# Annuler cette tâche à l’arrêt du bot et prévoir la reprise après erreur réseau.
task = asyncio.create_task(website.poll(handle_site_command))
```

Ne mettre `HERITAGE_BOT_COMMANDS_ENABLED=1` qu’après l’implémentation de ce
gestionnaire. Une action confirmée dans le site n’est pas encore confirmée dans
Discord : consulter les opérations en attente. La livraison peut se répéter
après une panne ; le gestionnaire doit donc être idempotent sur `command['id']`.
Ne pas renvoyer en événement entrant une action déjà reçue du site.

Le propriétaire peut consulter `/api/admin/bot-connection` après connexion au site :
dernier événement reçu et nombre d’opérations non confirmées. Aucun secret n’y figure.

## Vérifications

```bash
.venv/bin/python -m pytest tests/test_bot_connection.py -q
node tests/local_business.mjs
node tests/browser_pages.mjs
```

Les tests n’appellent pas ton vrai bot et n’utilisent pas tes secrets.
Une connexion réelle Discord reste à valider après remplissage du `.env` et
configuration de l’adresse publique.

Références : [OAuth2 Discord](https://github.com/discord/discord-api-docs/blob/main/developers/topics/oauth2.mdx),
[événements discord.py](https://discordpy.readthedocs.io/en/latest/api.html#discord.on_member_update).
