# L’Héritage — site unique

## Ouvrir le site

Depuis `/home/dojojo/Documents/bot_blanchiment`, une seule commande :

```bash
./lancer-site.sh
```

Adresse : **http://127.0.0.1:8081/**. Le lancement réutilise un site déjà actif et évite le message « Address already in use ». Depuis le dossier `site/`, `./run.sh` est le même point de démarrage. Ne pas lancer `http.server` : l’interface a besoin de son backend pour les comptes et les droits.

Le regroupement conserve le mode local actuel, la base, les sessions, la configuration privée, les photos, les droits et les logs. Il ne déclenche pas de mise en ligne ni de synchronisation métier bidirectionnelle avec le bot. Les mentions de prévisualisation ci-dessous décrivent toujours cette séparation des données et ce mode de fonctionnement, pas un autre site à lancer.


## Accès individuels et révocations

Le Conseil des Accès permet maintenant de révoquer un compte sans modifier ses rôles Discord, et de créer des accès personnels par pseudo et code. Voir le [guide des accès individuels](ACCES-INDIVIDUELS.md) pour l’utilisation, les protections et les tests.

## Préparation Supabase

Le choix d’une base commune en ligne pour le site et le bot, avec sauvegardes PC, est consigné dans [SUPABASE-PREPARATION.md](SUPABASE-PREPARATION.md). Aucun projet distant n’est encore créé ou raccordé. Le document détaille les adaptations nécessaires, l’environnement de test et la validation avant bascule. La preview continue d’utiliser SQLite.

## Chargement, listes et doubles envois

L’ouverture affiche un seul écran d’attente pendant la vérification `/api/me`, puis le préchargement groupé `/api/bootstrap` de **tous les espaces autorisés**. La navigation ordinaire utilise ensuite ces réponses en mémoire, sans requête de données ni indicateur entre les pages. Les vues privées ne sont stockées ni dans localStorage, ni dans un cache HTTP. Les recherches sont déclenchées après 300 ms sans frappe ; les échecs restent visibles avec « Réessayer ». Les formulaires conservent leurs valeurs et verrouillent leur bouton pendant l’envoi.

Le groupe initial contient les mêmes projections que `/api/pages/{page}?view=screen` : première page de 50 éléments par défaut (20 événements des ventes), filtres et totaux calculés sur toute la sélection. Il ne télécharge pas l’intégralité des anciennes archives ni les détails du journal permanent. Une recherche, une autre page de résultats, une ancienne semaine ou un classement sélectionné est chargé à la demande et conservé séparément en mémoire. Les archives Google Sheets restent chargées à l’ouverture du volet ; le catalogue véhicules à l’ouverture du formulaire Tombola. L’export demande explicitement toutes les lignes. Ces demandes supplémentaires conservent un indicateur si elles prennent du temps ; les anciennes réponses sans `view` restent compatibles.

Après une opération, toutes les variantes des espaces concernés sont invalidées puis leurs vues de départ sont rechargées dans un seul groupe ciblé. Un rafraîchissement en arrière-plan toutes les 60 secondes récupère aussi les changements faits ailleurs. Les droits sont contrôlés par `/api/me` toutes les 10 secondes lorsque l’onglet est visible ; après 30 secondes sans confirmation, la prochaine navigation doit refaire cette vérification. Un retour dans un onglet longtemps masqué confirme également la session avant restitution. Compte, rôle ou permissions modifiés : ancien cache supprimé. Les écritures et chaque API restent autorisées côté serveur. Les visites réelles sont journalisées par `POST /api/visits/{page}`, sans bloquer l’affichage ; un préchargement ne crée aucune fausse visite.

SQLite ne renvoie au code Python que les collections nécessaires à la vue, au moyen de `json_extract`/`json_type` ; Équipe et Mon Registre ne lisent pas les données métier. Les dossiers restent stockés dans le document JSON existant : leurs filtres sont appliqués côté serveur, sans prétendre disposer d’un index SQL sur leurs noms. Les index ajoutés concernent les membres, les sessions, leurs expirations, les états OAuth, les événements signés et les recherches d’audit par auteur/type. Les clés primaires déjà indexées sont réutilisées pour les identifiants.

Les mutations métier portent un en-tête `Idempotency-Key`. La table `operation_keys` conserve l’empreinte de l’envoi par utilisateur ; son écriture, la mutation et sa trace sont dans la même transaction. Une répétition identique retourne le résultat sans refaire l’opération, y compris après redémarrage. Réutiliser une clé avec un autre contenu est refusé. La clé est conservée par le navigateur si le résultat est incertain ; aucune écriture n’est rejouée automatiquement. Les anciens clients sans clé restent compatibles ; la protection serveur contre les répétitions nécessite cet en-tête, envoyé par l’interface actuelle.

Les index et la table de déduplication sont des ajouts à la base existante. Ils ne suppriment ni ne réinitialisent les dossiers, comptes, permissions ou journaux. Une sauvegarde de la base est prise avant leur activation sur la prévisualisation utilisée.

## Messages en cas de panne

La page affiche une alerte persistante lors d’une panne réseau, d’une erreur serveur, d’une réponse illisible ou d’une erreur JavaScript inattendue. Le chargement des requêtes ordinaires est limité à 20 secondes ; la copie du bot dispose de 150 secondes pour respecter son traitement plus long. Le bouton « Réessayer » recharge uniquement les informations : une écriture dont le résultat est incertain n’est jamais renvoyée automatiquement. Les champs du formulaire restent remplis ; vérifier l’historique avant de soumettre à nouveau une opération dont l’enregistrement n’a pas pu être confirmé.

Les messages ne montrent pas de trace technique ou de réponse serveur brute. Une photo ou une vidéo manquante n’est pas annoncée comme une panne complète du site. Cette protection nécessite que la page ait déjà été chargée : si le serveur est arrêté avant la première ouverture, le navigateur affiche sa propre erreur de connexion.

## Désactivation temporaire de la connexion Discord

Dans le fichier privé `.env`, `HERITAGE_LOCAL_PREVIEW=1` active un profil de test distinct des comptes Discord. Redémarrer `./run.sh`, puis ouvrir `http://127.0.0.1:8081` : le tableau de bord est accessible sans autorisation Discord. Aucun jeton ou compte Discord existant n’est remplacé. Les sessions réelles sont conservées. Les formulaires gardent leur protection CSRF et les essais restent dans la base de prévisualisation.

Ce mode est limité à l’accès direct depuis la machine locale sur le port 8081. Une adresse publique, un client distant ou les en-têtes d’un proxy/tunnel sont refusés. Avant toute mise en ligne, remettre **`HERITAGE_LOCAL_PREVIEW=0` et redémarrer** : la connexion Discord et ses vérifications habituelles reprennent. Ne pas placer de proxy masquant l’origine des connexions devant ce mode de développement.

Depuis le 25 octobre 2026, ce dossier `site/` contient l’unique version utilisable de L’Héritage. L’ancien site statique a été retiré et conservé seulement dans une archive privée sous `../archives/`. Le bot garde son propre fonctionnement. L’interface, les images, les animations et les formulaires sont repris dans `static/`. Les données métier sont enregistrées dans la base privée de test. Les exemples initiaux peuvent être remplacés par une copie des données réelles du bot ; les opérations effectuées ici restent locales.

## Démarrage rapide

```bash
cd /home/dojojo/Documents/bot_blanchiment/site
.venv/bin/python scripts/configure_oauth.py
./run.sh
```

Ouvrir **http://127.0.0.1:8081/**. La preview utilise le design actuel ; la variante visuelle expérimentale a été retirée.

Si le serveur de test tourne déjà, arrêter uniquement ce serveur avant de relancer `run.sh`. Aucun redémarrage du bot n’est nécessaire pour les vérifications REST.

Sur une nouvelle machine :

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
cp .env.example .env
chmod 600 .env
.venv/bin/python scripts/configure_oauth.py
./run.sh
```

## Configuration OAuth2

Dans le Developer Portal, ouvrir l’application **1551475154159271978**, puis **OAuth2 → Redirects**, et enregistrer exactement :

```text
http://127.0.0.1:8081/auth/callback
```

L’assistant local configure le Client Secret et le jeton du bot sans les afficher. Il peut importer uniquement `DISCORD_TOKEN` depuis le fichier privé existant du bot. Ne jamais copier ces secrets dans une discussion, dans `static/` ou dans un dépôt. Le Client Secret OAuth2 et le jeton du bot sont deux secrets différents. Une modification du fichier privé `.env` nécessite le redémarrage du serveur de test.

Le flux officiel utilise `identify` et `guilds.members.read`, une valeur `state` aléatoire liée à un cookie et consommée une seule fois, puis vérifie l’identité et l’appartenance au serveur `1500958425281204305`. Cette méthode ne nécessite aucun mot de passe du site. Les accès individuels par code sont distincts. Aucun second bot ni changement de profil Discord.

La connexion Discord nécessite désormais le rôle Employé `1500960060203859989`, configuré côté serveur par `HERITAGE_EMPLOYEE_ROLE_ID`. Le compte suprême est exempté de ce rôle, mais doit toujours appartenir au serveur. Ce rôle est une condition de connexion ; il ne donne aucune autorisation de page à lui seul. Le rôle Discord prioritaire reste responsable des accès configurés dans le Conseil. Si le rôle Employé est retiré, toutes les sessions du membre sont révoquées à la prochaine vérification Discord (cache de 30 secondes par défaut, au maximum 60 secondes selon la configuration). Le connecteur optionnel peut invalider ce cache immédiatement ; il reste séparé du bot en production.

## Comptes et droits

- Administrateur Suprême : **356404251905228802**, fixé côté serveur. Aucun rôle Discord, pseudo ou champ du navigateur ne donne ce statut.
- Les employés authentifiés et le compte suprême disposent de **Mon Registre**. Les autres pages sont refusées par défaut tant que leur rôle prioritaire n’est pas configuré.
- Un seul rôle compte : le plus élevé selon la position Discord ; à égalité, ordre Discord des snowflakes. `@everyone` sert de base si le membre ne possède aucun rôle supérieur. Un rôle supérieur non configuré interdit l’accès même si un rôle inférieur est autorisé.
- **Le Conseil des Accès** gère les rôles, les permissions, les comptes et les journaux. Il est exclusivement réservé à l’Administrateur Suprême.

Dans le Conseil, les pastilles du haut servent à retenir les rôles du domaine. « Appliquer les rôles » affiche leurs colonnes dans le tableau des accès. Les pages sont en lignes ; chaque case autorise ou interdit une page au rôle de sa colonne. Enregistrer les autorisations applique la grille côté serveur. Un nouveau rôle n’est pas retenu et ne possède aucun accès privé. Retirer un rôle supprime ses autorisations ; le retenir à nouveau commence sans accès. Le rôle prioritaire reste toujours déterminé sur tous les rôles Discord du membre, même lorsqu’il n’est pas retenu dans la grille : aucun repli sur un rôle inférieur n’est possible. Mon Registre reste accessible aux employés autorisés et le compte suprême conserve ses privilèges. La migration initiale conserve les autorisations déjà configurées dans cette prévisualisation.
- Les pages existantes sont découvertes dans le registre `const pages` de la copie d’`app.js`. Les nouveaux espaces déclarés sont refusés par défaut. Toute nouvelle API non classée est réservée au Suprême jusqu’à son raccordement à une page protégée.
- Les sessions sont stockées côté serveur ; le cookie contient un identifiant opaque, HttpOnly, SameSite=Lax, Secure en HTTPS. Durée : 30 jours, renouvelée automatiquement après vérification des accès. Les actions vérifient également l’origine et un jeton CSRF.
- Les jetons OAuth2 persistés sont chiffrés avec une clé privée locale. Aucune donnée privée ou liste complète de l’état métier n’est envoyée à une page non autorisée.

## Synchronisation Discord

Le backend vérifie les rôles et l’appartenance via l’API Discord du bot existant (`GET /guilds/{guild}/members/{user}`). L’identifiant du membre provient exclusivement de l’identité OAuth2 vérifiée ou de la session côté serveur. Aucun accès n’est accordé si cette vérification échoue. Les erreurs journalisées contiennent uniquement l’étape, le statut HTTP et le code Discord numérique ; aucun jeton ni réponse brute. Les lectures interrompues par un problème réseau ou une réponse 5xx sont réessayées une seule fois. Les erreurs 429 sont signalées avec le délai fourni par Discord. Le cache est limité à **30 secondes** par défaut, configurable entre 0 et 60 secondes. La suppression d’un rôle ou le départ du serveur est donc pris en compte sans déconnexion manuelle, au prochain contrôle. Quand le cache est périmé et Discord indisponible, les accès privés sont suspendus.

Le connecteur optionnel `integration/heritage_access_cog.py` se charge dans le bot **existant** pour une invalidation immédiate des caches. **Il n’est pas installé dans le bot en production.** Sa validation et son activation nécessitent l’accord avant mise en production. Il écoute les changements de rôles, départs de membres et événements de rôles, puis envoie des notifications signées HMAC, horodatées et protégées contre les rejeux. Les notifications invalident les vérifications ; elles ne permettent pas au navigateur d’accorder des permissions.

Pour un futur déploiement du connecteur : configurer côté bot `HERITAGE_ACCESS_URL`, `HERITAGE_CONNECTOR_SECRET` (même secret partagé privé) et éventuellement `HERITAGE_GUILD_ID`. Une liaison distante doit utiliser HTTPS. Charger l’extension dans le `setup_hook` du bot après validation ; aucun second client Discord n’est lancé.

## Données et séparation de la production

- `data/heritage-test.sqlite3` : comptes, rôles, permissions, sessions, audits et état métier fictif.
- `data/tokens.key` : clé privée de chiffrement des jetons, à conserver avec les sauvegardes.
- `data/avatars/` : photos personnelles privées ; seuls de véritables JPEG/PNG/WebP de moins de 1 Mo sont acceptés, décodés et réencodés en PNG sans métadonnées.
- `data/backup-*.sqlite3` : sauvegarde avant la réinitialisation administrative des données métier de test. Les comptes ne sont pas supprimés par cette action.
- `.env` : configuration privée de test. Ces fichiers sont exclus de Git et ne sont jamais servis comme fichiers publics.

Le serveur ne lit ni n’écrit les classeurs Google Sheets, les fiches Discord ou les JSON métier du bot. Les fonctions de vente, machines et tombola s’exécutent dans la base de test ; elles ne constituent pas encore une source de comptabilité commune à la production. Les anciens dossiers du navigateur principal restent intacts et ne sont pas importés automatiquement dans les comptes.

## Vérifications

Le [dernier audit après préchargement](AUDIT-APRES-PRECHARGEMENT-2026-10-24.md) détaille les correctifs supplémentaires et les 288 tests Python réussis. Le [bilan précédent](AUDIT-COMPLET-2026-10-24.md) et le [complément de préchargement](PRECHARGEMENT-2026-10-24.md) restent disponibles comme historique.

```bash
.venv/bin/python -m pytest -q
.venv/bin/python tests/browser_preload.py
.venv/bin/python tests/browser_frontend.py
.venv/bin/python tests/browser_workflows.py
.venv/bin/python tests/browser_failures.py
.venv/bin/python tests/browser_audit.py
.venv/bin/python scripts/verify_restore.py
.venv/bin/python scripts/verify_load.py
.venv/bin/python scripts/audit_dependencies.py
```

Les tests utilisent un Discord simulé et des bases temporaires : OAuth2, état à usage unique, appartenance, priorité unique des rôles, absence de cumul, CSRF, sessions, révocation, erreurs Discord, administration Suprême, profils, images invalides, notifications signées, limites des requêtes et opérations métier existantes.

La vérification navigateur couvre la connexion avec un fournisseur simulé dans un serveur éphémère isolé, le profil, les permissions, la création d’un blanchiment, les graphiques de statistiques, la navigation refusée et l’affichage mobile. Elle ne remplace pas l’autorisation réelle à effectuer depuis ton compte sur le portail Discord.

Exécuter les parcours Firefox successivement. Le contrôle Chromium séparé et ses binaires temporaires sont documentés dans [tests/CHROMIUM.md](tests/CHROMIUM.md). `verify_load.py` démarre un serveur temporaire pour 154 requêtes avec dix accès simultanés ; il ne cible pas le port 8081 actif. `audit_dependencies.py` transmet uniquement les noms et versions publics du verrou à l’API OSV ; un échec réseau renvoie un audit incomplet, jamais un résultat sain. Les contrôles de trafic des fournisseurs du site restent distincts de cet outil d’audit.

L’environnement requiert Python 3.11 ou plus récent. Pillow est verrouillé en 13.0.0 et cryptography en 50.0.2 après vérification des avis de sécurité et tests de compatibilité, y compris déchiffrement des anciens jetons. L’environnement du bot n’est pas modifié.

Les dépendances validées sont figées dans `requirements.lock`. La base de prévisualisation est distincte : aucune migration de données de production n’a été appliquée. La suppression de cet environnement de test n’affecte pas le site principal ; conserver ses fichiers privés si les comptes de test doivent être réutilisés.

`scripts/verify_restore.py` vérifie une restauration dans des dossiers temporaires privés : sauvegardes SQLite natives, clé de chiffrement, configuration et avatars, contrôle d’intégrité, déchiffrement des jetons, anciens logs et ouverture des dix pages. Il lit seulement les sources et n’appelle pas Discord ou Google Sheets. Les parcours Firefox utilisent également des bases temporaires et ne lisent pas le fichier privé réel. Une sauvegarde automatique hors du PC reste à configurer séparément.

## Avant une mise en production

Attendre l’accord du propriétaire. Prévoir le domaine HTTPS, la redirection OAuth2 correspondante, les variables privées du service, la sauvegarde de la base et de sa clé, la migration contrôlée des données métier, et l’activation validée du connecteur dans le bot. Aucun de ces changements de production n’est réalisé par cette prévisualisation.

Références : [Discord OAuth2](https://docs.discord.com/developers/topics/oauth2), [API User](https://docs.discord.com/developers/resources/user), [API des membres du serveur](https://docs.discord.com/developers/resources/guild#get-guild-member), [Limitations Discord](https://docs.discord.com/developers/topics/rate-limits), [Intents discord.py](https://discordpy.readthedocs.io/en/stable/intents.html), [FastAPI](https://fastapi.tiangolo.com/).

## Connexion persistante

La session est conservée pendant 30 jours (`HERITAGE_SESSION_DAYS`, de 1 à 90 jours) avec un cookie HttpOnly persistant. Elle se renouvelle après un accès authentifié réussi (au plus une fois par jour avec la durée par défaut) ; les sessions existantes plus courtes sont prolongées lors de leur prochain accès valide. La fermeture du navigateur et le redémarrage du serveur ne nécessitent pas de nouvelle autorisation Discord tant que le cookie et la session restent valides. La connexion et la réouverture à l’adresse d’accueil conduisent au Tableau de bord. Si le rôle n’y a pas accès, Mon Registre est utilisé. Les liens directs vers une page autorisée restent utilisables. Les permissions restent toujours vérifiées côté serveur. Le renouvellement des jetons OAuth2 se fait côté serveur. Le retrait du rôle Employé, le départ du serveur, la déconnexion ou l’expiration bloquent toujours l’accès. Une panne temporaire de Discord suspend l’accès sans effacer la session et ne la prolonge pas.

## Copie des données du bot

Le bouton **Actualiser depuis le bot** dans Statistiques est réservé au compte suprême. Il lit les fichiers métier locaux, les onglets actuels et archives des deux Google Sheets, et les fiches Sales du salon Discord. La connexion Google utilise exclusivement le scope `spreadsheets.readonly`. Aucun bot supplémentaire n’est lancé et aucune source n’est modifiée. Le script `scripts/export_bot_snapshot.py` utilise l’environnement `../venv/bin/python` déjà installé pour le bot. Les instantanés sont conservés dans `data/bot-snapshot-*.json`, privés et non servis par le site.

L’actualisation est manuelle afin de conserver les essais entre deux imports. Une sauvegarde SQLite précède chaque remplacement des données métier. Les comptes, photos, sessions et autorisations restent conservés. Si la lecture échoue ou si un autre essai modifie les données pendant la collecte, l’import n’écrase pas l’état courant.

Le classement reprend directement `machine_weekly_stats.json` : utilisateurs Discord, nombres de lancements et archives hebdomadaires. Un lancement compte une fois comme dans le bot, indépendamment de la récupération et du montant, sans multiplication par cinq. Les essais de lancement/annulation mettent à jour uniquement le compteur de test. L’import conserve d’abord les montants de progression effectivement affichés sur les fiches Discord. Les essais locaux touchant aux ventes ou machines déclenchent ensuite une réconciliation avec les quatre fonctions pures du bot extraites par AST, sans importer ni démarrer son application Discord. Les lignes historiques sans preuve de récupération ne créditent pas arbitrairement les dossiers. Les informations absentes des anciennes feuilles restent indiquées comme non renseignées.

La page Équipe affiche la photo personnalisée du compte, sinon l’avatar Discord. Les photos personnelles sont servies uniquement aux utilisateurs autorisés à voir Équipe ; le chemin de stockage privé n’est pas exposé.

Référence de lecture : [Google Sheets batchGet et scope de lecture seule](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/batchGet).


## Limites de trafic et d’appels externes

Ces protections sont activées dans la **preview sur 8081**, côté serveur, pour tous les navigateurs. Les réglages figurent dans `.env.example` ; les copier dans le fichier privé `.env` uniquement pour les modifier, puis redémarrer.

| Compteur | Valeur par défaut | Variable |
|---|---:|---|
| Toutes les requêtes par adresse IP, fichiers compris | 180 / minute | `HERITAGE_VISITOR_PER_MINUTE` |
| Envois POST/PUT/PATCH/DELETE par adresse IP, hors logs de navigation | 30 / minute | `HERITAGE_VISITOR_WRITES_PER_MINUTE` |
| Début et retour OAuth2 par adresse IP, cumulés | 10 / 10 minutes | `HERITAGE_VISITOR_AUTH_PER_TEN_MINUTES` |
| Discord, tous les utilisateurs du site réunis | 120 / minute et 10 000 / jour | `HERITAGE_DISCORD_PER_MINUTE`, `HERITAGE_DISCORD_PER_DAY` |
| Google, export de test et authentification inclus | 30 / minute et 500 / jour | `HERITAGE_GOOGLE_PER_MINUTE`, `HERITAGE_GOOGLE_PER_DAY` |
| Tentatives d’import depuis le bot, échecs compris | 3 / heure | `HERITAGE_SYNC_PER_HOUR` |

Les fenêtres sont fixes et alignées sur l’heure UTC (jour réinitialisé à 00:00 UTC), sans boucle d’attente ni reprise automatique des écritures. Chaque tentative réseau Discord, y compris un retry, consomme le budget avant son départ. Le transport de l’export Google compte également chaque tentative HTTP, redirection et renouvellement d’authentification, sans retries internes invisibles. Les imports Google restent en lecture seule. Le bot existant utilise toujours son propre transport : ses opérations ne sont pas limitées par la preview.

Au dépassement visiteur : HTTP **429**, message français et `Retry-After`. Au plafond fournisseur : HTTP **503**, raison `api_budget_exhausted` et `Retry-After`. Le frontend suspend les rappels vers le chemin concerné pendant ce délai. Quand une vérification Discord nécessaire est bloquée, aucun accès privé supplémentaire n’est accordé ; la session reste conservée. L’import interrompu conserve la copie métier précédente. Ces plafonds ne sont pas des budgets monétaires chez les fournisseurs.

Les compteurs atomiques sont dans `data/traffic-limits.sqlite3`, fichier privé partagé entre serveur et sous-processus d’export. Ils survivent aux redémarrages et fonctionnent entre processus utilisant ce même fichier. Seuls les compteurs expirés sont purgés ; cela ne concerne pas les logs ni les archives métier. Les adresses IP sont hachées dans ces compteurs. Changer de navigateur, cookie ou en-tête `X-Forwarded-For` ne remet pas le budget à zéro. Les personnes partageant une même adresse IP partagent cette limite ; changer réellement de connexion change l’IP.

Les visiteurs utilisent de petits blocs de **8 tickets déjà débités durablement** avant utilisation, avec un cache local borné à 512 entrées. Cela évite une validation sur disque pour chaque CSS ou image. Plusieurs règles restent réservées atomiquement ; plusieurs processus ne peuvent pas dépasser le plafond commun. Un arrêt, une éviction du cache ou un changement de plafond peut perdre quelques tickets inutilisés jusqu’à la fin de la fenêtre : la limite devient temporairement plus conservatrice, elle n’est jamais augmentée. Les quotas Discord, Google et imports restent comptés exactement appel par appel. Les accès SQLite attendus pendant une requête sont exécutés hors de la boucle HTTP.

`run.sh` désactive l’interprétation des en-têtes proxy. Avant un futur hébergement derrière un proxy, configurer explicitement un proxy de confiance qui remplace les en-têtes entrants et ne permet pas l’accès direct au serveur. Sinon tous les visiteurs derrière ce proxy partageraient sa limite. Avec plusieurs serveurs sur plusieurs machines, prévoir un stockage commun adapté (par exemple Redis). Une limite applicative ne remplace pas une protection contre la saturation réseau en amont.


## Règle du lot de machines

Un cycle regroupe toujours les 5 machines et dure 4 h 45. Le serveur refuse toute récupération tant que cette durée, calculée depuis l’heure de lancement enregistrée, n’est pas écoulée. Le bouton devient disponible à la fin du compteur ; il faut confirmer la récupération par une action dédiée avant le prochain lancement. Un lancement ne récupère jamais implicitement le lot précédent, y compris si un ancien navigateur envoie `confirmPrevious`.

La vérification et la création sont effectuées dans la même transaction SQLite : deux lancements simultanés avec des identifiants différents ne créent pas deux lots actifs. Répéter une récupération déjà enregistrée conserve son premier auteur et son horodatage, sans second crédit ni seconde opération métier. Un autre employé autorisé peut toujours récupérer le lot après la fin. Les annulations explicites et les lignes historiques non suivies restent distinctes des lots actifs. Les corrections d’heure existantes restent des opérations séparées ; la règle de récupération utilise l’heure enregistrée après une telle correction.


## Journal permanent

La page **Journal permanent** est découverte comme un nouvel espace privé. Elle est accessible au Suprême, ainsi qu’au profil local de test, et refusée aux autres rôles par défaut. Le Conseil des Accès permet d’en accorder l’accès. Cet accès donne la lecture du journal de **tous les espaces**, qui peut contenir des valeurs financières et des profils ; aucune fonction de modification ou de suppression n’est proposée.

Événements couverts :

- Connexions, déconnexions, refus d’authentification et d’autorisation, contrôles CSRF et limitations de trafic.
- Créations, corrections, annulations, restitutions, récupérations, tombola et clôtures hebdomadaires.
- Profils et références des avatars, permissions, rôles Discord synchronisés et révocations.
- Imports depuis le bot, réinitialisations, lectures des données et exports, consultations d’un événement du journal.
- Requêtes en erreur et erreurs navigateur signalées après ouverture d’une session. Les erreurs réseau, scripts et délais n’envoient ni pile d’exception ni contenu brut.

Les mutations métier et leurs changements sont écrits **dans la même transaction**. Le journal conserve l’identifiant et le nom de l’auteur au moment de l’action, la date serveur, le résultat et un identifiant de requête pour relier les événements. Chaque champ modifié conserve sa valeur complète avant et après ; une liste modifiée n’est pas tronquée. Les créations et suppressions distinguent une valeur absente d’une valeur nulle. Les imports et resets conservent leurs changements et leur sauvegarde. Les secrets, cookies, signatures et jetons ne font jamais partie des snapshots de profils ni des corps de requêtes journalisés. Le fil d’activité limité à 1 000 éléments reste une vue de présentation distincte ; il n’est plus la source du journal permanent.

La liste charge 50 événements à la fois (maximum API 100), par curseur d’identifiant décroissant. Filtres : auteur Discord, recherche par nom/action/fiche, type, espace, résultat et dates inclusives à Bruxelles. Les détails avant/après sont chargés uniquement à l’ouverture d’un événement. Les lectures techniques `/api/me`, statut et notifications du lot ne créent pas de fausses visites ; l’interface marque les changements de page pour les distinguer des rechargements de données. Les accès directs aux API de données et aux exports restent journalisés côté serveur.

Les signalements navigateur sont identifiés comme tels : leur date locale est indicative, la date de réception serveur fait foi. Une erreur réseau est placée dans une file locale liée au compte puis renvoyée au retour de la connexion ; une clé persistante évite de créer deux signalements si le résultat de l’envoi était incertain. Les répétitions d’une même catégorie sur une même page sont regroupées sur 30 secondes. Cette file contient uniquement une catégorie, la page, une date et un identifiant, aucun secret. Un navigateur qui n’exécute pas JavaScript, un stockage local effacé ou un arrêt avant transmission ne peuvent pas fournir une télémétrie rétroactive.

Stockage : table SQLite `audit`, sans purge automatique. Des triggers bloquent UPDATE et DELETE, y compris via les connexions applicatives. Avant la première activation sur une base existante, une sauvegarde privée `data/backup-before-permanent-audit-*.sqlite3` est créée automatiquement. Les anciennes lignes sont conservées à l’identique : leurs valeurs avant/après manquantes ne sont pas inventées. Les sauvegardes SQLite complètes existantes emportent le journal ; une stratégie automatique hors machine et des essais de restauration restent à prévoir.

Ces protections empêchent l’interface et le code applicatif de réécrire le journal. Elles ne constituent pas une garantie cryptographique contre un administrateur ayant le contrôle complet des fichiers du serveur. En cas d’échec de l’écriture du journal de mutation, la transaction métier est annulée. Un disque totalement indisponible ne peut pas enregistrer sa propre panne : le serveur renvoie alors une erreur générique.


## Navigation plus rapide

Les pages déjà consultées (tableau de bord, blanchiments, machines, tombola, statistiques, équipe et historique) sont conservées **30 secondes en mémoire dans l’onglet**, avec leurs filtres et leur pagination. Le cache est limité à 12 réponses et environ 4 Mio de texte ; il n’est jamais écrit dans le stockage persistant du navigateur. Aucune page non consultée n’est préchargée.

Chaque navigation utilise **un seul GET de données autorisé**, qui vérifie la session, le rôle prioritaire et l’autorisation actuelle. Le navigateur peut transmettre la version de sa réponse mémorisée ; le serveur recalcule la vue et répond 304 sans corps lorsqu’elle est identique, après les vérifications. La version est liée à l’identité et au rôle vérifiés côté serveur. Les données mémorisées ne sont affichées qu’après cette réponse, avec contrôle de l’identité et du rôle retournés. Une réponse refusée ou indisponible bloque le cache. Les vérifications Discord conservent leur politique de cache serveur existante ; le cache de navigation ne remplace pas ce contrôle.

Il n’y a plus de contrôle léger suivi d’un second téléchargement. Une réponse identique conserve le DOM en place lorsqu’on actualise la page déjà affichée ; sinon les sections modifiées sont remplacées. Les envois métier invalident les pages liées et actualisent la page courante sans effacer d’abord son contenu. Les resets, imports, changements d’accès et déconnexions vident le cache. Les profils modifiés invalident l’équipe. Les profils, le Conseil et le journal permanent ne sont pas mis en cache de navigation. Au démarrage, `/api/me` fournit aussi le mode et la configuration ; le Conseil reçoit rôles, accès et comptes dans une seule réponse de page.

L’animation de chargement du contenu apparaît après **180 ms** seulement. Les réponses rapides ne la font pas clignoter. Une page déjà visible reste affichée pendant son actualisation, avec un indicateur discret si la réponse tarde. Les erreurs et les révocations suppriment les données réutilisables ; les actions ne sont pas rejouées automatiquement. Le menu et la photo du compte ne sont plus reconstruits toutes les dix secondes quand ils sont inchangés.

Le journal conserve une seule consultation par navigation, y compris sur réponse 304. Les logs HTTP concurrents peuvent partager une transaction, dans une file bornée : **chaque réponse attend le COMMIT durable de son log avant ses en-têtes**. Une déconnexion du visiteur n’annule pas un log déjà en file ; l’arrêt normal du serveur attend la fin des écritures. Les mutations et leurs valeurs avant/après restent dans leur transaction métier atomique. Aucun passage des données permanentes en mémoire volatile, aucune purge automatique, aucune réduction de la durabilité SQLite.

Vérification Firefox après activation, même parcours que l’audit : document initial complètement chargé en **0,91 s contre 4,16 s**, rechargement en **0,68 s contre 4,03 s** ; retour vers Blanchiments terminé en **0,15 s contre environ 0,50 s**, Conseil en **0,14 s contre 0,72 s**. Mesures locales indicatives d’un parcours, sans garantie sur tous les appareils ou réseaux. Le test isolé vérifie aussi qu’une réponse volontairement retardée ne fait jamais afficher le cache avant l’autorisation, ainsi que révocations, changements externes, filtres, expiration et invalidations après écriture.
