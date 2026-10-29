# Handoff technique — moteur Machines commun

Audit de lecture du 29 octobre 2026, fuseau Europe/Brussels. Périmètre : `machine_operations.py`, appels Machines de `bot.py`, points de contexte dans `bot_guilds.py` et raccordement immédiat dans `bot_website_bridge.py`. Aucun changement de code, test relancé, accès Google/Discord, lecture des secrets ou exécution métier pendant cet audit. Les limites ci-dessous sont des observations du code et des scénarios déduits, pas des incidents démontrés sur le serveur réel.

## 1. API et appels existants

Dans `bot.py` :

| Entrée | Ligne | Contrat |
|---|---:|---|
| `machine_service()` | 2114 | Instancie paresseusement `MachineOperations(globals())` dans le namespace du serveur. L'initialisation crée/ouvre le journal SQLite ; ce n'est pas un simple accesseur sans effet disque. |
| `async machine_execute(action, actor, values, *, operation_id, machine_id=None, site_record_id=None)` | 2122 | Délègue au moteur. Renvoie un dictionnaire explicite de résultat ou lève une exception. Aucun faux `discord.Interaction`. |
| `machine_snapshot(record)` | 2127 | Snapshot d'un rappel ou d'un ID ; inclut données du rappel, auteur, références, révision. |
| `async recover_pending_machine_operations()` | 2131 | Reprise contrôlée du journal avec le membre présent dans le cache Discord. |

Actions reconnues par le moteur (`machine_operations.py:23`, `execute:139`) : `add-machine`, `recover`, `unrecover`, `edit-machine-time`, `cancel-machine`.

Les callbacks Discord actuels passent tous par `machine_execute` :

- `MachineModal.on_submit`, `bot.py:2143` : `add-machine`, `values.amount`, ID `discord:<interaction.id>` ; defer privé, puis confirmation ou erreur.
- `PreviousMachineRecoveryConfirmView.yes`, `bot.py:2635` : `recover` de la machine précédente. Après le defer et la récupération, un bouton permet d'ouvrir le formulaire de lancement. Il y a donc un clic supplémentaire par rapport à l'ancien envoi immédiat du modal.
- `MachineTimeEditModal.on_submit`, `bot.py:2680` : `edit-machine-time`, `values.launchTime`.
- `MachineLaunchView.cancel_machine`, `bot.py:2760` : `cancel-machine`.
- `MachineRecoveredView.toggle_recovered`, `bot.py:2804` : `recover` ou `unrecover`, avec `expected_recovered` pour refuser un vieux bouton.

`check_previous_machine_before_launch` (`bot.py:2607`) fournit le précontrôle visuel, mais le moteur effectue aussi le contrôle sous verrou lors de la création d'une nouvelle opération. Le helper historique `set_machine_recovered_state` (`bot.py:2533`) reste présent et testé ; les callbacks ci-dessus ne l'appellent plus. Les appels directs aux anciens helpers bas niveau restent techniquement possibles et contournent le journal commun.

Côté connecteur, `MachineWebsiteBridge.process_command` appelle le même `namespace['machine_execute']` (`bot_website_bridge.py:267`) avec `operation_id='site:'+command_id`, l'auteur Discord vérifié et la correspondance site → machine. Le moteur lui-même ne consomme pas HTTP.

## 2. Règles métier et identité

- Montant par défaut et maximum : 1 000 000 $, strictement positif (`bot.py:73`, moteur `amount:129`). Un lot du site représentant cinq machines demeure une seule opération du bot, un montant total, un compteur et un délai : aucune multiplication par cinq dans le moteur.
- Le parseur conserve la convention historique consistant à enlever espaces ASCII, points et virgules ; ce n'est pas un parseur de valeurs décimales. Booléens et types autres que texte/entier sont refusés.
- Un nouveau lancement est refusé si une machine non récupérée existe, hors tests/suivis historiques supprimés des rappels automatiques (`latest_unrecovered_machine`, `bot.py:2508`).
- Le moteur conserve le comportement Discord : `recover` peut intervenir avant l'heure de fin ; `unrecover` ne refuse pas à lui seul l'existence d'un autre lot actif. Ne pas décrire une interdiction universelle de récupération anticipée.
- L'auteur est un véritable `discord.Member`, avec `actor.guild.id == GUILD_ID`, module Machines actif et au moins un rôle de `MACHINE_ROLES` (`authorize:67`). Être administrateur seul ne remplace pas ce dernier contrôle.
- L'ID permanent du lanceur est `user_id` ; le nom est une présentation `user_name`. La récupération et l'annulation conservent également les IDs de leurs auteurs, sans changer le lanceur.
- Le membre fourni au moteur n'est pas refetché par celui-ci. Le connecteur vérifie les nouveaux auteurs par REST ; la reprise au démarrage utilise `guild.get_member`, donc le cache. Un membre absent du cache est ignoré ; un membre sans rôle requis est refusé.
- Le runtime de `bot_guilds.py` contrôle la révision de configuration, le serveur et les accès aux classeurs (`_channel:214`, `assert_sheet:224`). Le moteur recontrôle à plusieurs étapes ; ce n'est pas une transaction de permissions indivisible sur tous les appels réseau.
- Le salon est Messageable et appartient au serveur ; un rappel existant ou une reprise réutilise son `channel_id` durable (`channel:114`, `execute:239`). Le rôle à notifier doit exister avant l'écriture d'un nouveau lancement. Il n'est pas requis pour les mutations ordinaires.

## 3. Persistance et verrous

Le chemin du journal est calculé depuis `REMINDERS_FILE.resolve().with_name('machine_operations.sqlite3')` (`machine_operations.py:40`). Pour un namespace configuré, cela suit son dossier de données ; pour l'ancien serveur dont les fichiers restent à la racine, le journal se trouve à la racine. Ne pas annoncer un chemin unique commun à tous les serveurs.

Schéma réellement présent :

```sql
CREATE TABLE IF NOT EXISTS machine_operations(
  id TEXT PRIMARY KEY,
  fingerprint TEXT NOT NULL,
  body TEXT NOT NULL
);
```

Le fichier est mis en mode 0600. `fingerprint` est un SHA-256 JSON canonique du serveur, de l'ID auteur, de l'action, des valeurs, de l'ID machine et de l'ID site. Le même ID avec un autre contenu donne `operation_conflict`. Un ID terminé avec la même empreinte renvoie le résultat mémorisé sans réexécuter les étapes, après contrôle d'autorisation.

`body` contient notamment `stage`, `action`, `effects`, `values`, `actor_id`, les IDs, `record`, éventuellement `original` et `result`. Pour l'adoption : auteur et date du contrôle sont aussi enregistrés.

`operation_lock(path)` (`machine_operations.py:32`) partage un `asyncio.Lock` par boucle et chemin absolu, y compris entre deux moteurs reconstruits après un changement de configuration. Ce verrou est **local au processus et à la boucle**, pas un verrou interprocessus sur Discord/Google. `reset_machine_week_everything` (`bot.py:635`) prend ce même verrou et reporte la clôture s'il existe une opération incomplète autre que `stage=new`.

Autres persistances conservées : `machine_reminders.json`, `machine_weekly_stats.json`, état de clôture Machines et stockage Google Sheets ou SQLite local du bot. Les JSON sont écrits par fichier temporaire puis `replace` (`save_reminders:713`, `save_machine_stats:2196`). Ces fichiers et le journal ne participent pas à une transaction commune ; les écritures JSON n'appellent pas `fsync`.

## 4. Étapes d'un lancement et garanties exactes

Ordre dans `launch` (`machine_operations.py:273`) :

1. Plan `new` durable : ID machine déterministe à partir de l'ID opération, auteur, montant, horaires et génération du suivi.
2. `storage_inflight` persisté avant `add_machine_to_sheet`. Une réussite avec référence de ligne devient `stored`. Une erreur ou interruption à résultat non prouvé devient `storage_uncertain` ou reste `storage_inflight`.
3. `message_inflight` avant publication par le client Discord du bot existant. La carte contient les vues persistantes et le rôle configuré. Succès avec IDs durables → `published`. Erreur ambiguë → `message_uncertain`.
4. Suivi persistant (`effects.tracking`).
5. Compteur (`effects.counter`), avec marqueur atomique dans le même JSON que l'incrément.
6. Programmation du rappel (`effects.scheduled`).
7. Journal Discord secondaire, puis `execution_confirmed=True` persisté, retrait de `pending_operation_id`, `stage=done` et résultat durable.

Une nouvelle opération non terminée avec effets commencés bloque les nouveaux lancements ; une mutation incomplète bloque une autre mutation de la même machine. Le connecteur exclut les rappels avec `operation_id`/`pending_operation_id` dont `execution_confirmed` n'est pas vrai (`bot_website_bridge.py:294`).

Une écriture de stockage ambiguë n'est jamais répétée automatiquement. Un envoi ambigu cherche seulement une carte du bot portant le custom ID déterministe dans l'historique (`adopt_message:259`) : une carte retrouvée est adoptée ; son absence ne provoque pas un second envoi. Cela privilégie l'absence de doublon à une reprise automatique garantie.

Le journal Discord secondaire n'est pas une condition de succès. Son marqueur est écrit avant la tentative et une erreur est seulement journalisée : ce message peut donc être manquant et n'est pas automatiquement retenté.

## 5. Mutations, références et compteurs

`change` (`machine_operations.py:335`) mémorise `changing`, puis les étapes `storage`, `tracking`, éventuellement `counter`, annule/reprogramme les tâches nécessaires et édite les cartes connues. L'état reste non confirmé si un effet requis échoue. Une reprise réutilise les horaires et timestamps déjà mémorisés.

- `recover`/`unrecover` modifient le rappel et ses auteurs/timestamps, les cartes et les relances ; ils ne modifient pas le montant ni le compteur des lancements.
- `cancel-machine` conserve l'historique, marque annulé/récupéré/suppression des rappels, vide B/C/E/H sans supprimer physiquement la ligne, décrémente une seule fois le compteur du lanceur et remplace les contrôles par une relance. Une seconde annulation ne vide pas à nouveau une ligne réutilisée.
- `edit-machine-time` corrige date/heure en B/E, conserve les autres données, recalcule la fin et resynchronise le rappel/carte.
- Les écritures sur une génération archivée ou une référence dont date/heure/montant ne correspondent plus sont évitées. Le rappel reçoit `storage_warning` ; l'action Discord peut néanmoins être confirmée. Cela ne signifie donc pas qu'une cellule archivée a été corrigée ou effacée.
- `machine_sheet_reference_matches` (`bot.py:2471`) vérifie une identité de contenu, pas un ID permanent enregistré dans le Sheet. Le nom H n'est exigé que pour l'adoption administrative. Le contrôle n'est pas une preuve unique face à deux lignes de mêmes date/heure/montant ou deux personnes homonymes.

`increment_machine_stat` (`bot.py:2356`) utilise `applied_operations['launch:'+operation_id]` ; `decrement_machine_stat` (`bot.py:2397`) utilise `cancel:`. Le marqueur et le compteur sont sauvés ensemble avant l'édition du classement Discord. Une reprise d'un ancien lancement non compté appartenant à une autre semaine n'incrémente pas la semaine courante ni les archives figées ; elle pose le marqueur `historical` et produit un log. Le vieux compteur peut donc ne pas être rétroactivement complété.

## 6. Horaires, rappels et redémarrage

`Europe/Brussels`, affichage secondaire `America/Toronto`, durée réelle 4 h 45 (`bot.py:50`). `machine_time_shift:55` passe par UTC pour traverser les changements d'heure ; l'affichage inclut les dates Belgique/Québec (`machine_display_time:62`). `corrected_machine_launch:2659` choisit le jour voisin le plus proche du lancement initial ; le moteur rejette une heure inexistante au printemps.

`schedule_reminder` (`bot.py:3246`) n'ajoute une tâche que si l'ID n'est pas déjà dans `reminder_tasks`. La programmation mémoire n'est pas durable à elle seule : `restore_machine_views_and_reminders` (`5076`) repart des rappels JSON au setup et réinstalle les vues. `on_ready` appelle ensuite `recover_pending_machine_operations` (`5731`) avant de lancer le scan d'historique.

`recover_pending` (`machine_operations.py:430`) ignore `new`, `storage_inflight`, `storage_uncertain`, retrouve l'auteur dans le cache et reprend les autres étapes prouvées. Un compte parti, introuvable ou sans droits n'est pas remplacé par le propriétaire ou le bot.

`reminder_worker` (`bot.py:3124`) attend la différence réelle UTC jusqu'à la fin, recharge l'état, refuse les machines récupérées/annulées/supprimées des rappels, envoie sur Discord le montant à récupérer de 80 %, puis conserve les références. `machine_recovery_repeat_loop` (`3270`) vérifie toutes les minutes et relance environ toutes les quinze minutes tant que non récupéré. Les messages de rappel ciblent actuellement le rôle configuré ; l'ID du lanceur sert au suivi, ce n'est pas une garantie de mention individuelle systématique.

## 7. Adoption administrative et limites de reprise

Entrée interne : `await machine_service().adopt_storage(operation_id, row, actor=member)` (`machine_operations.py:447`). Aucune commande Discord, route site ou interface d'administration n'expose actuellement cette méthode.

Conditions : rôle Machines habituel **et** Gérer le serveur/Administrateur ; opération `add-machine` en état d'écriture ambiguë ; ligne valide dans la même génération ; pas de rappel actif revendiquant déjà cette ligne ; date, heure, montant et nom H correspondants. La méthode n'ajoute rien au suivi et passe le journal à `stored`, avec l'auteur/date d'adoption. Une reprise normale reste ensuite nécessaire.

Pour une demande site, le journal du connecteur peut déjà être terminal `uncertain`. `process_command` renvoie alors son résultat mémorisé sans réappeler le moteur (`bot_website_bridge.py:230`). L'adoption du seul journal Machines ne réinitialise pas ce deuxième journal. Il faut un traitement opérateur contrôlé des deux états ; ne pas recommander de relancer aveuglément avec un nouvel ID.

## 8. Insuffisances identifiées à conserver dans le handoff

1. **Reprise de `stage=new` et simultanéité** : le contrôle de machine précédente n'est fait que lors de la création du journal (`execute:158–167`). Un échec réseau avant les effets peut laisser A à `new`; ces états n'empêchent pas un lancement B. La relivraison de A charge son plan et passe directement à `launch:276` sans refaire le contrôle. Scénario déduit : deux machines actives malgré le verrou. Pas reproduit dans cet audit.
2. **Tous les écrivains JSON ne prennent pas le verrou commun** : la boucle des relances et le scan d'historique chargent une liste puis font des appels réseau et réécrivent cette liste (`bot.py:3275`, `3363`, `5371`, fin du scan). Ils peuvent écraser un lancement ou une mutation apparus pendant leurs attentes. Le premier `reminder_worker` recharge la liste avant sauvegarde, mais remplace son objet machine par une version issue d'avant l'envoi (`3208–3213`) et peut écraser des champs récents de cette même machine. Une publication de relance déjà en vol peut également survivre à une récupération/annulation. Les contrôles des actions utilisateur seuls ne prouvent donc pas une absence globale de concurrence.
3. **Rappels et changement de salon** : les mutations suivent bien `record.channel_id`, mais les deux workers de rappel utilisent encore la constante courante `MACHINE_REMINDER_CHANNEL_ID` (`3150`, `3317`). Après reconfiguration, les prochains rappels peuvent partir dans un autre salon que la carte initiale.
4. **Absence de transaction globale / multiprocessus** : le verrou asyncio n'arrête pas une seconde instance du bot, un opérateur Google ou un autre écrivain externe. SQLite, JSON, stockage et Discord n'ont pas de commit atomique commun ; les garanties ne doivent pas être présentées comme un « exactly once » distribué absolu.
5. **Blocages conservateurs et outil opérateur incomplet** : une écriture incertaine bloque les nouveaux lancements et la clôture. Une carte introuvable après envoi ambigu peut rester indéfiniment en attente. Le cache membre, les permissions et l'accès à l'historique peuvent empêcher les reprises. Il n'existe pas d'interface complète pour abandonner/résoudre tous ces états, ni de reprise automatique du deuxième journal après adoption.
6. **Correction d'heure d'une machine déjà notifiée** : le moteur ne remet pas nécessairement `finished_notified`/`last_reminder_at` à zéro lorsqu'une fin corrigée redevient future. Après redémarrage, le restaurateur peut donc ne pas programmer le premier timer et laisser le traitement à la boucle de relance. Le délai/format exact du prochain rappel n'est pas garanti dans ce cas.
7. **Confirmation et cartes manquantes** : `render` ignore les messages 404 ou sans embed (`390–399`) et peut terminer l'opération sans modification visible de ces cartes. La carte de lancement a été requise au lancement, mais la confirmation d'une mutation ne prouve pas l'existence actuelle de chaque ancien message.
8. **Chargement tolérant du suivi** : `load_reminders` retourne une liste vide si le JSON est illisible (`704`). Cette tolérance peut masquer une corruption puis permettre à une écriture ultérieure de remplacer l'historique ; elle ne constitue pas une restauration vérifiée.
9. **Révisions et états historiques** : les cinq actions augmentent la révision du rappel, mais les writers historiques de rappels ne suivent pas tous ce compteur. Le connecteur maintient sa propre version de projection ; ne pas confondre les deux révisions.

Ces points sont rapportés, sans correction pendant cette tâche de handoff.

## 9. Preuves de tests et absence de validation métier réelle

`test_machine_operations.py` contient actuellement 18 scénarios simulés : identité permanente malgré noms identiques, permissions/serveur/montant, simultanéité des deux interfaces, doublons/restart, écriture ambiguë, adoption de ligne contrôlée, adoption de carte après timeout, refus de second envoi sans preuve, compteur après panne, reprise entre stockage et publication, annulation après réutilisation de ligne, récupération/non-récupération, confirmation après édition Discord, correction autour de minuit, mauvaise référence, changement de salon, changement de semaine.

Artefacts antérieurs lus comme texte :

- `/tmp/machines-final-bot-tests.log` : `Ran 148 tests in 17.717s`, `OK`.
- `/tmp/machine-core-final-tests.log` : ancien passage de 17 tests dédiés, `OK`.
- `/tmp/machine-counter-week-test.log` : test supplémentaire du passage de semaine, `OK`.
- `/tmp/machines-final-setup-tests.log` : 72 tests réussis, 2 subtests réussis.

Ces résultats reposent sur données temporaires et Discord/Google simulés ; ils ne prouvent pas un lancement réel depuis le site, un envoi réel du bot ou un rappel attendu pendant 4 h 45 sur le serveur. Aucun état actuel du service, aucun secret, aucune donnée personnelle ni opération réelle ne sont revendiqués par le présent audit.

Empreintes des sources lues pour dater exactement ce rapport :

- `machine_operations.py` : SHA-256 `e0741a4c17add3438ff447ac6e7e3e3efc21f2068fa5bd96db8a2d01bbd2ef86`.
- `bot.py` : SHA-256 `bd085626f837571458a55f62222449103bb20ff30682f0d3694f70238f30b0a8`.
- `test_machine_operations.py` : SHA-256 `6940be00580457f812f1d6c0f22dfa0feac8c6391f5b40095a534396ef251b12`.
