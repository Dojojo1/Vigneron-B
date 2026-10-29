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

## 4. Machines raccordées au bot existant

Le traitement métier des Machines utilise le bot, et non une simulation de
`discord.Interaction`. Les autres fonctions restent indépendantes et ne sont pas
mises en file comme si elles étaient déjà raccordées.

Côté bot, conserver `HERITAGE_BOT_BRIDGE_ENABLED=0` pendant l'installation ;
mettre `1` seulement lorsque le gestionnaire et les traitements du site sont
installés et vérifiés. Côté site, activer ensuite `HERITAGE_BOT_COMMANDS_ENABLED=1`.

Sur le site réel, `HERITAGE_BOT_COMMANDS_ENABLED=0` refuse les opérations Machines
avec « liaison indisponible ». Le mode `HERITAGE_LOCAL_PREVIEW=1` reste une
simulation locale explicite. Activer la file uniquement après installation du
consommateur dans le bot et des deux versions de ce protocole.

Une demande du site contient :

```text
id: identifiant de commande durable, 32 caractères hexadécimaux
body.version: 2
body.protocol: machines-v1
body.guildId: serveur Discord ciblé
body.page: machines
body.action: add-machine | recover | unrecover | edit-machine-time | cancel-machine
body.recordId: identifiant réservé de la fiche site
body.values: {amount: entier} ou {launchTime: HH:MM}, sinon {}
body.actor: {id: identifiant Discord permanent, name: nom du profil connecté}
body.record: fiche confirmée existante, ou null pour un lancement
```

Le choix d'un autre lanceur n'est plus proposé dans le formulaire connecté. Le
serveur conserve l'identifiant du profil qui valide ; le bot vérifie à nouveau
le membre et ses rôles. Un accès extérieur sans membre Discord est refusé
explicitement. Les noms ne servent jamais d'identifiant de compte.

Le site réserve la demande dans `bot_machine_jobs` sans modifier le montant,
l'heure ou le compteur confirmés de `domain_store`. L'état est affiché à part :
**En attente du bot**, **Confirmée par le bot**, **Échec**, ou **Échec partiel —
vérification nécessaire**. Les erreurs et l'indisponibilité de la liaison restent
visibles. L'écran Machines lit un état confirmé toutes les 30 secondes, ou toutes les
15 secondes lorsqu'une demande attend une réponse. Une seule lecture automatique
peut être en cours ; elle est suspendue si l'onglet est masqué, si un formulaire
est ouvert, pendant une saisie ou pendant un envoi. Les opérations effectuées
dans Discord apparaissent donc aussi sans changer de page. Un bouton permet
d'actualiser manuellement.

Seules les commandes présentes dans la nouvelle table de suivi sont délivrées.
Les anciennes commandes d'essai sans ce suivi restent conservées mais ne seront
jamais exécutées automatiquement. Une nouvelle activation ne transforme pas les
anciennes fiches du site en lancements Discord. Elles restent consultables comme
historiques non confirmés et ne participent pas aux compteurs confirmés.

### Confirmation et synchronisation

Le bot envoie `POST /internal/bot/events` signé avec `kind: machine_sync`, un
`eventId` stable pour la relivraison, et un objet `machine` :

```text
machineId, guildId, revision (entier monotone)
siteRecordId (facultatif pour une opération Discord)
actor: {id, name}
amount: montant TOTAL entier, de 1 à 1 000 000
launchedAt, finishAt: dates ISO avec fuseau, séparées de 4 h 45 réelles
recovered, cancelled: booléens
recoveredBy, cancelledBy: {name, id?}, facultatifs pour les historiques
recoveredAt, cancelledAt: dates ISO facultatives
storage: {sheetId?, worksheet?, row?, localRef?, warning?}
messages: {channelId?, launchMessageId?, finishMessageId?, messageIds?}
```

Pour une demande du site, conserver `siteRecordId` dans le snapshot et
`commandId` dans l'ACK. Le `commandId` de l'événement est facultatif : le
connecteur fourni dans le récapitulatif le retire du snapshot. Le serveur valide la
correspondance avec la fiche réservée et enregistre `bot_machine_links`. Pour une
opération Discord, une fiche est créée ou actualisée par l'identifiant stable de
la machine. Le montant et les dates réels sont repris tels quels : une récupération
ou un rafraîchissement ne relance jamais l'horloge. Un avertissement `storage.warning` de 300 caractères maximum est conservé et
affiché sur la fiche, par exemple lorsqu'une référence Google historique est
ambiguë et qu'aucune ligne n'a été modifiée. Une révision plus ancienne ne
remplace pas la plus récente ; une révision réutilisée avec un autre contenu est
refusée. Un événement entrant ne crée jamais une nouvelle commande sortante.

Un lancement représente toujours le lot entier : montant total habituel et
maximum 1 000 000 $, un cycle de 4 h 45 et une unité au classement. Le classement
confirmé groupe les opérations par ID Discord, même si deux membres ont le même
nom. Les données déjà importées ne sont pas incrémentées une deuxième fois.

Après succès, envoyer `POST /internal/bot/ack` :

```text
{guildId, commandId, status: applied, result: {machine: état_canonique}}
```

Le serveur exige `result.machine`, même si la fiche a déjà été synchronisée.
Il vérifie l'auteur et le montant d'un lancement, ainsi que l'état demandé
pour une récupération, un retour en non récupérée ou une annulation. Un ACK
terminal redélivré doit conserver le même statut, résultat et erreur.
Les projections et confirmations invalides sont annulées dans la même
transaction. Un échec
explicite utilise `status: failed`, un effet externe non prouvable utilise
`status: uncertain`, avec `error: {code, message}`. Ces états restent visibles et
ne sont pas rejoués automatiquement. Une panne partielle reprenable utilise
`status: pending` avec une erreur explicite : la commande reste livrable et le
bot reprend ses étapes durables sans recréer la ligne, la carte ni le compteur.
Une confirmation finale efface cette erreur de reprise.

Le bot conserve son journal d'exécution par serveur dans son espace de données :
les namespaces de `bot_guilds.py` ne partagent ni verrous, ni machines, ni mappings.
Un identifiant de commande déjà traité retrouve le même résultat après redémarrage.
Un état `uncertain` impose une vérification du stockage ou du message signalé avant
toute nouvelle tentative ; ne pas supprimer les journaux pour forcer un nouvel
essai. Consulter les logs du bot et la liste des commandes affichée sur le site.
La liaison démarre une seule tâche dans le client Discord existant et n'est pas
recréée à chaque reconnexion. Aucun nouveau bot ni service d'exécution n'est créé.

Le bot peut envoyer `kind: heartbeat` environ toutes les 30 secondes. L'état de
liaison affiche la dernière présence ; après 90 secondes sans présence elle est
présentée comme indisponible. Les trois routes internes exactes `/internal/bot/events`,
`/internal/bot/commands` et `/internal/bot/ack` disposent d'un budget distinct par
adresse, plafonné par `HERITAGE_VISITOR_PER_MINUTE` (180 par défaut). Elles ne
consomment pas les tickets d'écriture des visiteurs qui peuvent arriver par le
même proxy local. Elles restent limitées et chaque échange conserve sa vérification
HMAC ; les autres chemins gardent les quotas habituels.

Les pannes du site ne doivent jamais interrompre
les rappels Discord, qui restent gérés par le bot.

### Règles conservées et différences entre les anciennes interfaces

Le bot conserve la référence pour la récupération et la correction d'heure.
L'ancien site interdisait la récupération avant la fin de 4 h 45 et corrigeait
l'heure sur le même jour ; le bot permettait certaines récupérations anticipées
et savait corriger le jour autour de minuit. Le serveur connecté ne réapplique
pas ces anciennes mutations locales : il soumet la demande aux fonctions du bot.
Le bouton de récupération du site conserve actuellement le délai visuel de
4 h 45 ; le moteur/API du bot permet une récupération anticipée. Cette différence
reste à harmoniser explicitement.

En mode connecté, seuls les lots confirmés alimentent les allocations des
dossiers et les montants traités, dans les pages Sales, Overview, Stats et le
préchargement. Les anciennes fiches d'essai restent stockées sans participer
à ces calculs. Le mode aperçu conserve ses règles de simulation.

La réinitialisation des essais est masquée dans l'interface connectée et
refusée par le serveur lorsque des correspondances ou demandes Machines
existent. Elle ne sert pas à débloquer une opération liée au bot.

### État de cette fusion et correctifs du bot

Les changements côté site ont été fusionnés depuis le dossier `recap/` en
conservant l'attribution par profil et la correction du retour d'onglet. Ce
travail ne modifie pas le bot Linux, ses données ou les drapeaux du `.env`.
Les défauts de reprise et de concurrence du bot signalés dans le récapitulatif
restent à corriger avant la recette réelle. Voir
[la passation des correctifs du bot](PASSATION-CORRECTIFS-BOT.md).

Aucun secret ne doit être publié dans GitHub Pages. Le raccordement utilise
`HERITAGE_SITE_URL=http://127.0.0.1:8081` côté bot et le même
`HERITAGE_CONNECTOR_SECRET` privé dans les deux programmes ; les variables de
jeton Discord restent `DISCORD_TOKEN` pour le bot et `DISCORD_BOT_TOKEN` pour le
site. Le tunnel public n'est pas utilisé pour ce trafic local.

## Vérifications

```bash
.venv/bin/python -m pytest tests/test_bot_connection.py -q
node tests/local_business.mjs
node tests/machine_refresh.mjs
node tests/browser_pages.mjs
```

Les tests n’appellent pas ton vrai bot et n’utilisent pas tes secrets.
Une connexion réelle Discord reste à valider après remplissage du `.env` et
configuration de l’adresse publique.

Références : [OAuth2 Discord](https://github.com/discord/discord-api-docs/blob/main/developers/topics/oauth2.mdx),
[événements discord.py](https://discordpy.readthedocs.io/en/latest/api.html#discord.on_member_update).
