# Validation et état observé — audit en lecture seule

Audit effectué le **29 octobre 2026 vers 00:43, Europe/Brussels** (28 octobre vers 23:43 UTC). Aucune modification de code, configuration, donnée métier ou service n’a été effectuée pour cet audit. Aucun appel d’action Machines, aucune fausse interaction Discord et aucun lancement Google/Discord n’ont été créés.

## Service et réseau effectivement observés

Commande utilisée :

```bash
systemctl show blanchimentbot.service \
  -p ActiveState -p SubState -p MainPID -p WorkingDirectory -p ExecStart
ss -H -ltn '( sport = :8081 or sport = :8082 or sport = :8083 )'
```

Résultat :

- Service `blanchimentbot.service` : `active`, `running` ; MainPID observé `19391` (éphémère, ne pas l’utiliser comme configuration).
- Exécutable réel : `/home/dojojo/Documents/bot_blanchiment/venv/bin/python`.
- Argument programme réel : `/home/dojojo/Documents/bot_blanchiment/bot.py`.
- WorkingDirectory réel : `/home/dojojo/Documents/bot_blanchiment`.
- Ce processus du service est démarré depuis le 28 octobre à 23:59:28 CET ; il ne faut pas affirmer que le PID initial du déploiement du 28 est encore le PID actuel.
- Seul `127.0.0.1:8081` est en écoute parmi les trois ports vérifiés ; rien n’écoute sur 8082/8083.
- `GET http://127.0.0.1:8081/api/status` a renvoyé **HTTP 200**.
- Lecture filtrée du journal du service depuis `2026-10-28 22:55:00 UTC` : connexion Gateway et synchronisation `/setup` observées ; aucun traceback/import échoué ni diagnostic `[SITE MACHINES]` dans cette plage. Aucun log Gateway brut ni identifiant de session n’a été exposé.

## Configuration observée, sans valeurs privées

Seuls des booléens ont été émis à partir des fichiers privés, sans afficher leur contenu :

- `HERITAGE_BOT_BRIDGE_ENABLED` côté bot : activé.
- `HERITAGE_BOT_COMMANDS_ENABLED` côté site : activé.
- `HERITAGE_LOCAL_PREVIEW` côté site : désactivé.
- Le secret partagé est configuré (longueur suffisante) et identique entre les programmes.
- Le serveur Discord configuré pour le raccordement est identique des deux côtés.
- `DISCORD_TOKEN` et `DISCORD_BOT_TOKEN` désignent le même jeton de bot.

Aucune valeur de secret, jeton, clé Google, serveur/utilisateur privé ni fichier `.env` n’est reproduite ici.

## État agrégé des bases réellement présentes

Lecture SQLite avec `mode=ro`, sans afficher d’identité ni de fiche individuelle :

| Base | Observation à l’audit |
|---|---|
| Bot `data/website_bridge.sqlite3`, table `machines` | **134** correspondances/projections |
| Même table, projections dont `sent` est absent ou différent de `payload` | **0** en attente |
| Bot table `commands` | **0** commande site enregistrée |
| Site `data/heritage-test.sqlite3`, table `bot_machine_links` | **134** correspondances |
| Site table `bot_machine_jobs` | **0** commande Machines du site |
| Site metadata `bot_last_seen` | événement `heartbeat` récent, environ 31 secondes au prélèvement |

Ces observations confirment une communication réelle signée et une projection passive persistée des fiches existantes. Elles ne prouvent aucun lancement site → Discord : les deux journaux de commandes site restent vides.

### Observation nouvelle d’une récupération réelle, sans la déclencher

Le journal réel `machine_operations.sqlite3` à la racine contient **une opération `recover`, étape `done`**, dont l’identifiant d’opération porte le préfixe `discord:`. Une vérification interne, sans émettre les identifiants, noms, montants ni dates de la fiche :

- le résultat du moteur est récupéré ;
- la projection du bot est marquée envoyée ;
- le snapshot du site indique également récupéré et conserve le même `recoveredAt`.

Cela constitue une **observation passive d’une récupération Discord → site cohérente**, postérieure aux tests initiaux. Il serait faux d’affirmer qu’aucune opération réelle n’existe désormais ; il serait également faux de l’attribuer aux tests ou de prétendre que nous l’avons déclenchée. L’opérateur utilisateur n’a pas été identifié/exposé. Cette observation ne valide ni le lancement depuis le site, ni le cycle de rappel réel de 4 h 45, ni une annulation/édition d’heure réelle.

## Preuves de tests conservées

Les logs suivants sont présents dans `/tmp`. Ils datent du déploiement du **28 octobre 2026**, et n’ont pas été recréés lors de cet audit. Les dates ci-dessous sont les heures de modification des logs, converties en heure Bruxelles (UTC+1 à cette date).

| Commande exécutée | Résultat conservé | Log / heure locale |
|---|---|---|
| Depuis le bot : `timeout 100s venv/bin/python -m unittest discover -s . -p 'test_*.py' -q` | **148 tests, OK**, 17,717 s | `/tmp/machines-final-bot-tests.log`, 21:11:34 |
| Depuis le bot : `timeout 90s bot_setup/.venv/bin/python -m pytest bot_setup/tests test_guild_setup.py test_guild_sheets.py -q` | **72 passed**, 2 subtests passed, un avertissement | `/tmp/machines-final-setup-tests.log`, 21:11:24 |
| Depuis le bot : `timeout 50s venv/bin/python -m unittest test_bot_website_bridge test_machine_operations -q` | **41 tests, OK**, 6,418 s | `/tmp/machines-latest-tests.log`, 21:13:26 |
| Depuis le site installé : `timeout 120s .venv/bin/python -m pytest tests -q` | **292 passed, 1 failed, 1 skipped**, un avertissement | `/tmp/machines-real-site-final-tests.log`, 21:15:20 |
| Depuis le site : `timeout 30s .venv/bin/python -m pytest tests/test_bot_connection.py::test_new_connected_database_starts_without_demo_business_records -q` | **1 passed**, après correction de la fixture | `/tmp/machines-fresh-database-retest.log`, 21:15:43 |
| Depuis le site : `timeout 60s /home/dojojo/Documents/bot_blanchiment/venv/bin/python -m pytest tests/test_machine_bot_contract.py -q` | **4 passed**, un avertissement | `/tmp/machines-real-contract-final-tests.log`, 21:14:20 |

Une passe antérieure du site en staging est aussi conservée : `/tmp/site-machine-full-final.log`, **290 passed, 1 skipped**, 60,07 s. Ce n’est pas la même passe que celle effectuée sur les sources installées après les derniers ajouts.

### Échec de fixture et portée du résultat final du site

Le seul échec de la dernière passe complète installée était `test_new_connected_database_starts_without_demo_business_records` : `os.link` a échoué avec **Invalid cross-device link** en copiant les assets vers la base temporaire du test. Le test utilise désormais `link_or_copy`, qui conserve le lien si possible et utilise `shutil.copy2` sinon. Le test corrigé a été relancé et a réussi.

Le dossier peut donc annoncer que les **292 autres tests et ce test corrigé ont réussi**, mais ne doit pas inventer un log de passe complète ultérieure « 293 passed ». Aucun tel log n’a été retrouvé.

Le module ignoré dans le venv du site est le contrat croisé, qui dépend de `discord.py` ; le fichier fait `pytest.importorskip('discord')`. Les quatre tests de ce module ont bien été exécutés séparément dans le venv du bot, qui possède cette dépendance.

### Interface navigateur

L’historique du déploiement contient l’exécution réussie suivante :

```bash
cd /home/dojojo/Documents/vigneron_site
/home/dojojo/.vscode-server/cli/servers/Stable-e646868227c3e3a9e3f24277c8c7220be42c0be7/server/node tests/machine_refresh.mjs
```

Résultat historique : `OK: Discord snapshots refresh at 30s/15s, one request, hidden/form/input/submit pauses, storage warning escaped.` Le scénario utilise un environnement JavaScript VM et un backend simulé. Aucun log autonome de cette exécution n’a été conservé dans les fichiers examinés. Il ne faut pas le présenter comme un essai complet avec un vrai navigateur connecté à Discord ou au tunnel public.

## Ce que les tests simulent réellement

- `test_machine_operations.py` : `TemporaryDirectory`, faux `discord.Member`, `Mock`/`AsyncMock` pour salons, publications, stockage et planification ; vérification du moteur commun et de ses checkpoints.
- `test_bot_website_bridge.py` : SQLite temporaire, membre Discord simulé, client site simulé ; vérification d’identité, configuration courante, doublons, reprise, absence de confirmation d’opération partielle et cycle de vie du consommateur.
- Site `tests/test_machine_bot_contract.py` : vrais modules du contrat HMAC, `FastAPI TestClient`, SQLite temporaire ; `WebsiteClient` passe par un faux opener vers le TestClient, et Discord/Google restent simulés. Son commentaire précise qu’aucun `.env` privé ni base de production n’est chargé.
- Les tests ne prouvent pas la publication réelle d’une nouvelle carte de lancement ni l’émission réelle d’un rappel après 4 h 45.

## Limites de validation à transmettre

1. Aucun lancement complet réel site → bot → Discord → site n’a été créé par les tests ou cet audit.
2. Aucun test réel des cinq opérations depuis les deux interfaces n’a été mené par nous ; seule une récupération Discord → site a été observée passivement dans les données actuelles.
3. Aucun rappel réel de 4 h 45 n’a été déclenché pour validation ; les rappels habituels continuent hors de cet audit.
4. Cloudflare Tunnel et GitHub Pages n’ont pas été validés ici ; HTTP 200 loopback ne valide pas le chemin public, OAuth ou les cookies du navigateur.
5. Les résultats des suites datent du 28 octobre ; cet audit n’a pas relancé toute la suite sur les sources éventuellement modifiées depuis.
6. La présence du backend sur 8081 ne prouve pas sa supervision après redémarrage du PC. Le raccordement n’a pas installé de service système supplémentaire pour le site.

## Courte procédure réelle proposée, sans déclenchement automatique

À exécuter seulement par un responsable autorisé et avec une vraie opération à réaliser, après vérifier qu’aucun lot antérieur n’attend sa récupération :

1. Ouvrir la page Machines, vérifier la liaison en ligne et noter les compteurs avant opération.
2. Valider **une seule fois** un lancement depuis le compte Discord responsable ; conserver le `commandId` et le `recordId` de la réponse HTTP 200/JSON `pending: true`. Si la réponse est perdue, réutiliser la même `Idempotency-Key` et le même corps ; ne pas créer une nouvelle demande avec une nouvelle clé. Le retour dédupliqué ne renvoie actuellement que `ok`/`duplicate`, pas nécessairement le `commandId` original : retrouver l’état via la liste `machineCommands` de la page Machines.
3. Attendre le passage pending → applied/confirmed ; vérifier une seule carte Discord, le bon auteur, le montant total et un seul incrément. Ne pas recliquer pendant l’attente ou en cas d’erreur ambiguë.
4. Recharger la page ou attendre l’actualisation (30 s, 15 s si attente) ; comparer l’identifiant du bot, les références messages et les horaires conservés.
5. Lors de la fin réelle du lot, vérifier le rappel Discord puis réaliser une récupération et vérifier sa projection sur le site ; ne pas accélérer les horloges de production pour le test.
6. En cas de `pending` avec erreur, laisser la reprise livrer le même ID ; en `uncertain`, faire vérifier l’opération avant toute nouvelle tentative. Aucune suppression des bases de déduplication pour « débloquer » un essai.

Cette procédure reste à exécuter ; elle ne doit pas être formulée comme un test déjà réussi.
