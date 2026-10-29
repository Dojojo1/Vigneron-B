# Raccordement du bot au site — dossier de reprise du 29 octobre 2026

**État : implémentation Machines présente et activée, transport réel et projection passive vérifiés ; recette métier complète encore à faire.** Ce dossier décrit le code présent sur disque, pas seulement l’intention du travail précédent. Il ne déclare pas le raccordement terminé. Des limites de concurrence, de résolution des erreurs et de cohérence de certains compteurs restent à traiter.

Ce travail de récapitulation n’a modifié aucun code de production, configuration, service ou donnée métier. Il a lu les sources, créé ce dossier et vérifié les patchs/exemples sur des copies et bases temporaires, sans réseau. Aucun token, secret partagé, fichier `.env`, clé Google, base, sauvegarde privée ou fiche utilisateur réelle n’est fourni.

## 1. État réel du raccordement

| Fonction | Implémentation présente | Validation disponible |
|---|---|---|
| Lancement Discord | `MachineModal` appelle le moteur commun. | Tests simulés ; aucun nouveau lancement réel déclenché par nous pour validation. |
| Lancement site | Session site → file durable v2 → consommateur du bot → même moteur → snapshot signé → ACK. | Tests croisés avec vrais modules HMAC/FastAPI/SQLite, effets Discord/Google simulés. Aucun lancement site réel enregistré lors de l’audit. |
| Récupération | Action `recover` depuis les deux interfaces. | Simulation ; une récupération réelle d’origine Discord a aussi été observée passivement et retrouvée cohérente sur le site. |
| Retour en non récupérée | Action `unrecover`. | Simulation, pas de recette réelle faite par nous. |
| Correction d’heure | Action `edit-machine-time`, champ `launchTime`. | Simulation, y compris règles de date/fuseaux ; pas de correction réelle déclenchée pour test. |
| Annulation | Action `cancel-machine`. | Simulation, pas d’annulation réelle déclenchée pour test. |
| Cartes, vues, compteur, rappels | Moteur commun réutilisant les fonctions du bot existant. | Tests ; les rappels ordinaires restent actifs, mais aucune attente réelle de 4 h 45 n’a été organisée pour cette validation. |

Une opération site ne crée pas une autre machine métier : elle doit être associée à l’unique machine exécutée par le bot. Les snapshots synchronisent ID, véritable lanceur, montant total, horaires, états récupéré/annulé, opérateurs connus et références stockage/messages. Le site ne doit pas recalculer un nouveau lancement à la réception d’une récupération.

Un lot de cinq machines représente **un montant TOTAL par défaut et maximum de 1 000 000 $, un lancement au compteur et une durée réelle de 4 h 45**. Les métadonnées `machineCount=5` et `nominalUnitAmount=200000` ne multiplient rien.

Le moteur conserve les règles Discord : récupération anticipée possible ; édition d’heure choisissant le jour voisin le plus proche du lancement, utile autour de minuit. L’interface du site conserve toutefois encore un blocage visuel de récupération anticipée : cette différence UI/API reste à décider/corriger. Les heures des cartes restent Belgique et Québec/Montréal.

### Vérifications réelles en lecture seule

Au contrôle du 29 octobre, heure Bruxelles : service du bot actif, connexion Gateway et `/setup` observés, HTTP 200 sur le site, heartbeat signé récent, **134 correspondances de machines de chaque côté et zéro projection en attente**. Les tables de commandes site restent vides : cela valide le transport et la synchronisation passive, pas un lancement site → Discord.

Le journal du moteur contient une récupération `recover/done` d’origine `discord:` et sa projection cohérente sur le site. Nous ne l’avons pas déclenchée. Aucune identité, référence individuelle ou donnée métier de cette récupération n’est publiée ici.

Les limites détaillées sont dans les audits joints. Les risques déduits du code sont distingués des incidents réellement observés ; aucun des scénarios de concurrence ci-dessous n’est présenté comme un incident reproduit en production.

## 2. Code et fichiers réellement concernés

Racine du bot : `/home/dojojo/Documents/bot_blanchiment`.

| Chemin relatif bot | Nature et rôle |
|---|---|
| `bot.py` | Modifié : extraction de l’API commune, callbacks Machines, compteurs idempotents, contrôle des références Sheet, verrou de clôture, reprise dans `on_ready`, installation du connecteur après le runtime multi-serveurs. |
| `machine_operations.py` | Ajouté : moteur commun, journal/checkpoints, verrou, reprise et adoption administrative contrôlée d’une ligne. |
| `bot_website_bridge.py` | Ajouté : consommateur unique, contrôles serveur/auteur/rôles, inbox durable, mapping, révisions et projection passive. |
| `website_client.py` | Copie adaptée du client signé du site : transport et ACK enrichis ; identique à la copie actuelle côté site. |
| `test_machine_operations.py`, `test_bot_website_bridge.py` | Ajoutés : moteur et connecteur simulés. |
| `test_bot_local_storage.py` | Modifié : fixtures de membre/permissions compatibles avec le moteur partagé. |
| `.env.example`, `.gitignore` | Variables d’exemple et exclusions des nouvelles bases/sauvegardes privées. Aucun `.env` exporté. |
| `README.md`, `GUIDE-DOSSIERS.md`, `CONNEXION-SITE-MACHINES.md` | Documentation ajoutée/actualisée. |
| `.env` privé | Modifié lors du déploiement du 28 : configuration du raccordement. Contenu exclu. |

`bot_guilds.py` reste le runtime existant et **n’a pas été modifié pour ce raccordement**. Le connecteur enveloppe ses hooks après `install_multi_guild_runtime`, consulte le namespace courant à chaque demande et ne crée pas de second client Discord. Le `bot_setup/` existant n’est pas l’API d’exécution du site.

Racine du site : `/home/dojojo/Documents/vigneron_site`.

| Chemin relatif site | Rôle des changements |
|---|---|
| `backend/app.py` | Mise en file des Machines connectées au lieu de mutation locale ; projections de lecture et métadonnées de liaison. |
| `backend/bot_bridge.py` | Jobs v2, correspondances, `machine_sync`, heartbeat, quatre états ACK et validation. |
| `backend/domain.py` | Classement Machines dérivé des opérations confirmées par ID permanent. |
| `backend/views.py` | Synthèse confirmée, filtrage historique et avertissements de stockage. |
| `backend/traffic.py` | Quota limité distinct pour les trois routes internes exactes. |
| `connectors/website_client.py` | ACK enrichis et `WebsiteHTTPError.status`. |
| `static/app.js`, `static/secure.js` | Identité imposée, états de demande/liaison, avertissements et actualisation automatique. |
| `docs/CONNEXION-BOT.md` | Contrat et déploiement ; ce dossier précise ses écarts avec le code effectif. |
| `tests/machine_refresh.mjs`, `tests/test_machine_bridge.py`, `tests/test_machine_bot_contract.py` | Nouveaux tests. |
| `tests/test_bot_connection.py`, `tests/test_business.py`, `tests/test_business_preload_integrity.py`, `tests/test_employee_access.py`, `tests/test_loading_and_requests.py`, `tests/test_machine_lifecycle.py`, `tests/test_traffic_limits.py` | Tests adaptés/étendus ; une fixture de liens fichiers a été rendue compatible avec des systèmes de fichiers distincts. |
| `.env` privé | Activation et sortie du mode preview lors du déploiement. Contenu exclu. |

### Points d’appel principaux

- `bot.py:2114` : `machine_service()` ; `machine_execute(...)` à la ligne 2122 ; `machine_snapshot(...)` et `recover_pending_machine_operations()` juste après.
- Callbacks de `MachineModal`, `PreviousMachineRecoveryConfirmView`, `MachineTimeEditModal`, `MachineLaunchView.cancel_machine`, `MachineRecoveredView.toggle_recovered` → `machine_execute`.
- `MachineOperations.execute` → `.launch` ou `.change` ; `.recover_pending` au démarrage ; `.adopt_storage` uniquement pour résolution administrative explicite.
- Lancement : `add_machine_to_sheet`, `MachineLaunchView`, `save_reminders`, `increment_machine_stat`, `schedule_reminder`, journal Discord secondaire.
- Modifications : fonctions existantes d’écriture/correction Sheet, vues persistantes, actualisation des cartes, arrêt/reprogrammation des rappels, compteur de lancement/annulation.
- `MachineWebsiteBridge.process_command` → `namespace['machine_execute']` ; `.sync_machines` → `._canonical`/`BridgeStore.snapshot` → `._send` → `WebsiteClient.event('machine_sync', ...)`.
- Site `POST /api/actions/machines` → `BotBridge.queue_machine` ; routes internes → `BotBridge.handle`/`.event`/`.sync_machine`.

Les lignes correspondent à l’instantané fourni ; les empreintes sont dans `SOURCES-ORIGINALES.json`.

## 3. Contrat exact et exemples

Lire **`CONTRAT-COMMUNICATION.md`** : endpoints, méthodes, octets HMAC, types/regex, dates, ACK, événements, duplications et tableaux de projection. Le dossier **`exemples/`** fournit 21 corps JSON complets, tous fictifs, dont les six situations demandées : lancement site, confirmation, lancement Discord, récupération, annulation et échec.

Points à ne pas modifier par supposition :

1. `POST /api/actions/machines` retourne **HTTP 200 avec `pending:true`**, pas 202 et pas un lancement confirmé.
2. `GET /internal/bot/commands` ne prend pas de corps ni de paramètre de serveur : le site est associé à un seul serveur configuré ; le bot vérifie aussi `body.guildId`.
3. Les snapshots du bot actuel ne transportent normalement pas `commandId` : la corrélation utilise `siteRecordId`, l’event ID stable et l’ACK. Le backend accepte un `commandId` optionnel, sans l’exiger.
4. Le nouveau type métier à accepter est **`machine_sync`** ; le nouveau type de présence est **`heartbeat`**. `kind=action,page=machines` est refusé. Ne pas inventer d’événements séparés pour recover/cancel.
5. Les dates ISO du transport deviennent des millisecondes Unix dans la projection du site. `createdAt` des commandes reste en secondes Unix.
6. `result.machine` d’un ACK contient le snapshot canonique, pas le résultat interne snake_case du moteur.

### Correspondance durable des identifiants

| Identifiant/référence | Producteur et stockage |
|---|---|
| Commande site | UUID hex 32 caractères, `bot_commands.id`, `bot_machine_jobs.id`, inbox `commands.id` du bot. |
| Opération moteur | `site:<commandId>` ou `discord:<interaction.id>` ; clé du journal `machine_operations`. |
| Machine nouvelle | `machine-` + 24 premiers caractères du SHA256 de l’ID d’opération ; les anciens IDs sont conservés. |
| Fiche site issue du site | `site-<uuid32>` réservé avant exécution, puis `siteRecordId`. |
| Fiche issue de Discord | Mapping existant, sinon `bot-` + 24 premiers caractères SHA256 de `guildId:machineId`. |
| Stockage | `storage.sheetId`, `worksheet`, `row`, éventuellement référence locale/avertissement ; reprise du fichier Sheet configuré ou classeur local. Une référence historique ambiguë n’est pas une preuve d’écriture réussie. |
| Discord | `messages.channelId`, `launchMessageId`, `finishMessageId`, `messageIds` ; chaînes pour préserver la précision des grands IDs en JavaScript. |
| Révision | Révision de projection persistée par `BridgeStore`, départ à zéro et progression au changement de contenu ; distincte de la révision interne du rappel. |

Le lanceur `machine.actor` reste celui du lancement. Une récupération par une autre personne change `recoveredBy`, pas le lanceur. Le site déduit l’auteur de la session ; le bot refait un `guild.fetch_member` par ID, vérifie les rôles et le contexte courant. Il ignore `body.actor.name`, `body.record` et tout choix de lanceur comme sources d’autorité métier.

### Quand confirmer et comment reprendre

Le moteur marque le suivi confirmé après les étapes nécessaires, notamment stockage, carte, suivi, compteur et rappel planifié. Les nouveaux suivis partiels portent `execution_confirmed=false` et ne sont pas exportés comme confirmés. Le connecteur mémorise son résultat `applied`, envoie le snapshot, puis l’ACK. Une panne de transmission ne transforme pas ce résultat déjà exécuté en un nouvel échec métier.

Les erreurs reprenables conservent l’état de commande bot `started` et envoient un ACK site `pending` avec erreur. Les erreurs définitives donnent `failed`. Une écriture externe non prouvable donne `uncertain`, terminal côté site : intervention nécessaire, pas de relance aveugle.

Le journal conserve les étapes avant/après effets et les résultats. Les compteurs gardent des marqueurs d’application. Une carte dont la réponse d’envoi a été perdue peut être adoptée en retrouvant son custom ID stable. Aucun verrou distribué ou transaction atomique globale ne couvre Discord + Google + les deux SQLite. Les tests couvrent plusieurs reprises et doublons, pas toutes les concurrences possibles.

## 4. Adaptations côté site : terminées et restantes

### Déjà présentes dans les fichiers du site

- Vérification HMAC, nonce/horodatage, déduplication d’événements et révisions.
- File v2 limitée aux Machines et quatre états d’ACK.
- Réception/projection de `machine_sync`, sans créer de commande en retour.
- Identité du compte qui valide ; champ launcher ignoré ; accès extérieur sans membre refusé.
- En attente / confirmée / échec / échec partiel visibles, liaison indépendante du succès métier.
- Compteurs Machines basés sur les opérations confirmées et regroupées par ID Discord.
- Anciennes commandes sans job non délivrées ; anciennes fiches non rejouées, présentées comme non confirmées dans les lectures concernées.
- Actualisation visible toutes les 30 secondes, 15 si attente, suspendue pendant saisie/formulaire/onglet masqué ; une lecture automatique à la fois.

### À traiter avant une déclaration de recette complète

| Priorité | Limite réellement relevée | Travail à poursuivre |
|---|---|---|
| Haute | Une reprise moteur à `stage=new` ne refait pas le contrôle du lot précédent. Un autre lancement peut avoir réussi entre-temps. | Revalider les préconditions sous verrou à la reprise avant premier effet ; ajouter un test de ce scénario. Analyse de source, pas incident constaté. |
| Haute | Workers de rappels et restauration historique écrivent encore le JSON hors verrou commun, parfois après un await. | Étendre le mécanisme de mutation atomique/locking à ces chemins ; tester les écritures concurrentes. Analyse de source, pas incident constaté. |
| Haute | ACK `uncertain` terminal sans endpoint de résolution ; adoption du Sheet seule ne rouvre pas automatiquement les journaux. | Parcours administratif authentifié/audité, avec résolution coordonnée moteur + inbox bot + job/ACK site. Ne pas supprimer les bases pour forcer une reprise. |
| Haute | `domain.allocations/financial` utilise encore des anciens essais récupérés sans filtre de confirmation. | Exclure explicitement les machines non confirmées des calculs financiers connectés ; ne pas confondre avec le compteur Machines déjà filtré. |
| Haute | Aucun lancement site → Discord réel ni rappel de 4 h 45 validé. | Exécuter la procédure de recette finale sur une vraie opération autorisée. |
| Moyenne | Reset manuel des compteurs et archives du bot non synchronisés comme un état de statistiques autoritaire. | Définir un futur événement validé ou un état partagé pour statistiques/reset/archives ; le site actuel recalcule les lancements à partir des fiches. |
| Moyenne | ACK applied sans résultat peut être accepté avec un lien ancien ; doublon ACK ne compare que le statut. | Rendre explicite la preuve de résultat/révision/action et contrôler le résultat immuable sur relivraison. |
| Moyenne | `reset-test-data` efface l’état métier mais laisse liens et inbox : même snapshot peut rester dédupliqué sans reconstruire la fiche. | Concevoir restauration/resynchronisation cohérente ; ne pas utiliser ce reset en production pour migrer le raccordement. |
| Moyenne | UI bloque encore recover avant 4 h 45, contrairement au moteur/API connectée. | Décider et harmoniser cette règle, sans annoncer qu’elle est déjà identique partout. |
| Moyenne | Les workers de rappel utilisent le salon configuré courant, tandis que les mutations suivent le `channel_id` durable. | Traiter et tester le changement de salon pendant un lot en cours. |
| Faible | Duplicate `Idempotency-Key` ne redonne pas l’ID original ; nombre pending admin inclut des anciens jobs non livrables. | Retourner les références originales ; séparer les compteurs de jobs exécutables/anciens. |

Le helper `WebsiteClient.poll` reste générique et ne fournit pas les garanties du `MachineWebsiteBridge`. Ne pas le substituer au consommateur durable. Les notifications d’accès sont best effort ; seuls les snapshots Machines ont l’outbox décrite ici. Sale/blanchiments, restitutions et véhicules/tombola ne sont pas raccordés dans cette livraison : leur API locale ne prouve pas une opération Discord.

## 5. Configuration, fichiers à transférer et commandes

### Variables privées : noms et rôle seulement

| Projet | Variables nécessaires |
|---|---|
| Bot | `DISCORD_TOKEN` existant ; `HERITAGE_BOT_BRIDGE_ENABLED` ; `HERITAGE_SITE_URL` (`http://127.0.0.1:8081` si même PC) ; `HERITAGE_CONNECTOR_SECRET` ; `DISCORD_GUILD_ID`. |
| Site | `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID` existants ; `HERITAGE_CONNECTOR_SECRET`, `HERITAGE_BOT_COMMANDS_ENABLED`, `HERITAGE_LOCAL_PREVIEW=0`. |
| Accès du site existant | `HERITAGE_BASE_URL`, `HERITAGE_SUPREME_ID`, `HERITAGE_EMPLOYEE_ROLE_ID` ; éventuellement `HERITAGE_PUBLIC_BACKEND_URL` pour l’entrée GitHub/tunnel et `HERITAGE_SEED_DEMO_DATA=0` pour une nouvelle base vide. |
| Selon stockage | `GOOGLE_APPLICATION_CREDENTIALS` et accès Google existants du bot, seulement si cette fonction utilise Sheets. Aucune clé dans ce dossier. |
| Optionnels | `GUILD_SETUP_DB` commun au bot/setup ; quotas `HERITAGE_VISITOR_PER_MINUTE` et autres réglages déjà présents. |

Le secret doit être identique des deux côtés, au moins 32 caractères côté client. Les jetons désignent le même bot mais gardent leurs noms respectifs. Les deux `DISCORD_GUILD_ID` doivent correspondre au serveur voulu et à son runtime configuré ; aucune recherche par nom n’est admise. Le tunnel public ne sert pas au trafic local du connecteur.

**Activation :** garder les échanges désactivés pendant une installation incompatible ; n’activer `HERITAGE_BOT_COMMANDS_ENABLED` que lorsque le consommateur, les validations et les deux versions du contrat sont installés et testés. Au moment de cet audit, les deux commutateurs sont déjà activés et la présence est réelle. Cela ne vaut pas recette métier complète ; les limites de la section 4 restent ouvertes. Ce récapitulatif n’a pas changé ces réglages.

### Fichiers

Pour le bot Linux : `bot.py` avec son patch Machines, `machine_operations.py`, `bot_website_bridge.py`, `website_client.py`. Conserver ses modules existants, ses configurations et ses bases, notamment chaque `machine_operations.sqlite3` et `data/website_bridge.sqlite3`.

Pour le site Linux : les neuf fichiers d’exécution/documentation du tableau de la section 2, plus les tests pour revue. Les chemins complets se déduisent des deux racines précisées. Préserver `.env`, clé de session, base du site et tables de correspondance/inbox. Ne pas copier les fichiers du bot à la place des fichiers du site.

Le dossier `sources/` contient les copies génériques ; `patches/site-exact.patch` couvre les 19 fichiers changés du site depuis la sauvegarde préalable. Les fonctions/classes Machines de `bot.py` sont dans `patches/bot-machines.astpatch.json`, sans les constantes privées. `OMISSIONS.md` explique les omissions de fichiers entiers et l’anonymisation d’une valeur de fixture. Les sources d’exécution exportées sont exactes ; une seule fixture de test est explicitement anonymisée.

Ces patchs sont déjà présents dans les projets audités : **ne pas les réappliquer aveuglément sur ces mêmes sources**. Leur but est la transmission/revue ou une application contrôlée sur la copie antérieure correspondante. Le manifeste fournit des SHA256.

### Service du bot réellement exécuté

```text
Unité : blanchimentbot.service
WorkingDirectory : /home/dojojo/Documents/bot_blanchiment
ExecStart : /home/dojojo/Documents/bot_blanchiment/venv/bin/python /home/dojojo/Documents/bot_blanchiment/bot.py
```

Commandes de redémarrage, **fournies mais pas exécutées pendant ce récapitulatif** :

```bash
sudo systemctl restart blanchimentbot.service
sudo systemctl status blanchimentbot.service
journalctl -u blanchimentbot.service -f
```

Le site est un autre processus, sans nouveau service systemd installé ici. S’il est arrêté :

```bash
cd /home/dojojo/Documents/vigneron_site
./lancer-site.sh
```

Le script détecte un serveur existant ; ce n’est pas une commande de restart à chaud. S’il tourne dans un terminal, l’arrêter avec Ctrl+C puis relancer. Pour le processus détaché reconnu sur 8081, l’outil joint vérifie propriétaire, dossier, application et liaison loopback avant un SIGTERM ; il refuse un processus différent. Il relance le serveur au premier plan sans lire ni modifier les secrets :

```bash
python3 outils/redemarrer_site.py --root /home/dojojo/Documents/vigneron_site
python3 outils/redemarrer_site.py --root /home/dojojo/Documents/vigneron_site --restart
```

La première commande inspecte seulement. L’outil n’a pas été exécuté pour redémarrer un service pendant la préparation de ce dossier. L’accès public et sa configuration OAuth doivent être contrôlés séparément ; un HTTP 200 local ne valide pas Cloudflare/GitHub.

## 6. Validation : résultats et portée

Les commandes et logs datés se trouvent dans `audits/handoff-validation.md`. Résumé fidèle des essais du 28 octobre :

| Commande / environnement | Résultat conservé |
|---|---|
| Bot : `venv/bin/python -m unittest discover -s . -p 'test_*.py' -q` | **148 tests OK**. |
| Bot : `venv/bin/python -m unittest test_bot_website_bridge test_machine_operations -q` | **41 tests OK** après derniers ajustements. |
| Setup : `bot_setup/.venv/bin/python -m pytest bot_setup/tests test_guild_setup.py test_guild_sheets.py -q` | **72 passed**, deux sous-tests. |
| Site installé : `.venv/bin/python -m pytest tests -q` | **292 passed, 1 failed, 1 skipped**. Échec environnemental de copie par lien sur deux systèmes de fichiers. |
| Site : `.venv/bin/python -m pytest tests/test_bot_connection.py::test_new_connected_database_starts_without_demo_business_records -q` | **1 passed** après correction de cette fixture. Ne pas inventer une nouvelle passe complète « 293 passed ». |
| Site, avec le venv du bot : `/home/dojojo/Documents/bot_blanchiment/venv/bin/python -m pytest tests/test_machine_bot_contract.py -q` | **4 passed**. Module ignoré dans le venv du site où `discord.py` manque. |
| Node : `node tests/machine_refresh.mjs` | Scénario VM simulé OK ; ce n’est pas un navigateur réel connecté à Discord. |

Ces tests utilisent des données temporaires et Discord/Google simulés. Les quatre tests croisés utilisent les vrais modules de signature, FastAPI et SQLite, mais pas de carte Discord ni de Sheet réel. La suite complète n’a pas été relancée pendant ce travail de documentation ; les logs de la livraison précédente ont été vérifiés.

Vérifications supplémentaires du dossier le 29 octobre : application du patch site dans une copie temporaire des sources antérieures (19 fichiers), génération du patch bot donnant un résultat byte-identique au bot actuel, analyse de syntaxe, et **5 exemples d’événements + 6 ACK acceptés par le vrai backend signé en SQLite temporaire, sans réseau**. Ce sont des contrôles de documents/compatibilité, pas une validation Discord réelle.

Vérifications réelles : transport signé, heartbeat, projection passive des fiches et observation d’une récupération Discord → site cohérente. **Aucune nouvelle opération réelle n’a été déclenchée par nous pour les tests, la livraison ou ce récapitulatif.** La récupération observée n’est pas une action de cet audit. Le lancement réel depuis le site, les cinq actions dans les deux interfaces et l’émission d’un rappel réel après 4 h 45 restent à valider.

### Procédure courte de recette, encore à exécuter

À faire par un responsable, pour une véritable opération autorisée, après traitement des limites prioritaires :

1. Vérifier le bon serveur, l’auteur connecté, ses rôles, la liaison en ligne et l’absence de lot précédent à récupérer ; noter le compteur.
2. Valider **une seule fois** un lancement. Garder le même `Idempotency-Key` et le même corps en cas de réponse perdue. Conserver `commandId` et `recordId` ; si la réponse dédupliquée ne les contient pas, consulter `machineCommands`, sans créer une autre clé.
3. Attendre la même commande pending → applied et sa fiche confirmée. Vérifier **une seule ligne**, **une seule carte**, le véritable auteur, le montant total, **un seul incrément** et les mêmes horaires sur le site.
4. Recharger ou attendre la lecture de la page, sans relancer le lot. Vérifier la correspondance machine/messages et la conservation du lancement.
5. À la fin réelle des 4 h 45, vérifier le rappel Discord, effectuer la récupération une seule fois et constater son retour sur le site, même navigateur fermé pendant l’attente.
6. En `pending` avec erreur reprenable : laisser le même ID revenir. En `uncertain` : arrêter les nouveaux essais et résoudre les journaux de façon coordonnée. Ne pas supprimer les bases de déduplication et ne pas forcer un nouveau lancement pour masquer l’échec.
