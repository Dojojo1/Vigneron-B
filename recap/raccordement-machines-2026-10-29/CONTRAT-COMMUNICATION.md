# Contrat du site présent sur disque — audit du 29 octobre 2026

Périmètre : `/home/dojojo/Documents/vigneron_site`. Lecture du code uniquement ; aucune configuration privée ni base métier réelle inspectée, aucun changement de production. Les numéros de ligne cités correspondent aux fichiers présents au moment de cet audit. Les valeurs de plafond ci-dessous sont les **valeurs par défaut du code**, pas une affirmation sur les réglages du processus en cours. Les fichiers documentaires existants ne font pas autorité face au code.

## 1. Transport réellement implémenté

Sources : `backend/app.py:211`, `backend/bot_bridge.py:30`, `connectors/website_client.py:40`.

| Route | Méthode | Corps / réponse |
|---|---|---|
| `/internal/bot/commands` | GET | Client : aucun corps. Retour `{"commands":[{"id":...,"createdAt":... ,"body":{...}}]}`. |
| `/internal/bot/events` | POST | Objet JSON d’événement ; réponse selon le type, normalement `{"ok":true,...}`. |
| `/internal/bot/ack` | POST | Objet JSON d’accusé ; réponse `{"ok":true,"status":...}` ou doublon. |

La route FastAPI est déclarée pour GET et POST, puis vérifie ces trois seules combinaisons et produit HTTP 405 pour une autre combinaison qui atteint le gestionnaire. Ces trois chemins sont exemptés de session navigateur et de CSRF ; **ils restent protégés par HMAC**. Il n’y a pas de restriction d’adresse IP dans le gestionnaire. Ils peuvent être atteints via l’origine publique si le proxy les expose ; le client du bot peut employer l’origine loopback, indépendante du tunnel.

En-têtes :

- `X-Heritage-Timestamp` : horodatage Unix entier en secondes, texte correspondant à `[0-9]{1,12}` ; écart absolu entre horloge serveur et horodatage ≤ 60 secondes.
- `X-Heritage-Nonce` : `[a-f0-9]{32}`, le client produit `uuid.uuid4().hex`.
- `X-Heritage-Signature` : HMAC-SHA256 hexadécimal minuscule, `[a-f0-9]{64}`.
- POST : le client ajoute `Content-Type: application/json`.

Octets signés exactement :

```text
UTF8(METHOD + "\n" + PATH + "\n" + TIMESTAMP + "\n" + NONCE + "\n") + RAW_BODY
```

`PATH` est par exemple `/internal/bot/events`, sans origine ni paramètres de requête. `RAW_BODY` est le corps HTTP exact, pas un JSON reformaté. Le client le produit avec `json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()` ; **il ne trie pas les clés**. GET du client signe `b''`. Le serveur vérifie les octets reçus avec `hmac.compare_digest` avant de parser le JSON.

Le secret n’est pas un jeton Discord. Le client exige au moins 32 caractères et une origine HTTPS ou HTTP loopback (`localhost`, `127.0.0.1`, `::1`), sans identifiants, chemin fonctionnel, query ou fragment (`website_client.py:26`). Pas de suivi des redirections ; délai réseau 15 s ; réponse lue jusqu’à 2 MiB. Une réponse HTTP d’erreur devient `WebsiteHTTPError` avec attribut entier `.status`, sans corps de réponse ni secret. Les erreurs réseau et de décodage JSON ne sont pas converties en succès.

Toutes les requêtes traitées réservent le nonce dans `event_nonces` pour 120 secondes ; réutilisation HTTP 409. Cette réservation fait partie de la transaction de `bridge.handle` : un échec provoquant son rollback ne consomme pas durablement le nonce. Un retry normal doit générer une nouvelle signature/nonce, tout en conservant l’ID métier.

Le parseur commun du site rejette clés JSON répétées, NaN/Infinity et nombres flottants non finis (`app.py:98`). Corps POST/PUT/PATCH limité à 2 MiB, y compris fragmentés (`limits.py:3`). Les échanges passent sous `security.lock`, puis le travail SQLite s’exécute dans le threadpool (`app.py:218`).

## 2. Demande utilisateur → commande Machines

Source : `app.py:490`, `bot_bridge.py:56`.

L’utilisateur authentifié envoie :

```json
{"action":"add-machine","id":null,"values":{"amount":"1000000"}}
```

à `POST /api/actions/machines`, avec session, accès à la page et protection CSRF habituels (`Origin` exact de l’origine du site + `X-CSRF-Token`). La session et l’autorisation de page sont revérifiées dans la transaction. L’auteur est tiré du profil authentifié : `user.id` et `display_name or username`. Le navigateur ne peut pas choisir cet ID avec `values`.

En mode connecté (`local_preview == False`), ce POST **ne fait pas `domain.mutate`**, ne crée pas de machine confirmée et ne touche pas le compteur confirmé. Il appelle `queue_machine`. En mode prévisualisation locale, il conserve le vieux parcours purement local : ce parcours ne démontre pas une exécution du bot.

Conditions de mise en file :

- `actor_id` doit être une chaîne `[0-9]{1,24}` ; les comptes `guest-...` sont refusés explicitement HTTP 403.
- Action dans les cinq actions Machines ; inconnue HTTP 403.
- `bot_commands_enabled` et secret configuré requis, sinon HTTP 503. La présence d’un heartbeat récent n’est **pas** exigée pour mettre en file.
- Les clés de `values` commençant par `_` sont retirées. Pour lancement : seules `amount` et `launcher` sont acceptées, mais `launcher` est ensuite ignoré. Pour édition : seul `launchTime`. Pour les trois autres actions : aucun champ public.
- `add-machine` : `id` doit être absent/null ; montant normalisé par `domain.amount`, défaut 1 000 000, borne 1..1 000 000. Le normaliseur existant accepte nombres entiers ou nombres flottants entiers et retire espaces/points/virgules des représentations textuelles. Pas de multiplication par cinq.
- Les autres actions exigent un ID de fiche existant avec `botMachineId`, `botStatus == 'confirmed'`, et non annulée. Une récupération/non-récupération identique n’est pas dédupliquée à ce niveau ; c’est une nouvelle demande que le bot traite.
- `edit-machine-time` : `launchTime` chaîne correspondant à `(?:[01]?\d|2[0-3]):[0-5]\d` ; l’acceptation de l’heure réelle et de la date revient ensuite au bot.
- Une commande `pending` ou `uncertain` de lancement bloque un autre lancement. Pour une modification, une commande `pending`/`uncertain` de la même fiche bloque une autre modification. Le verrou est persistant et commun à tous les utilisateurs du site.

Retour de mise en file :

```json
{"ok":true,"pending":true,"commandId":"<32 hex>","recordId":"site-<32 hex>","status":"pending"}
```

`Idempotency-Key` facultatif : `[A-Za-z0-9_-]{16,100}`, lié au profil utilisateur et au hash canonique de la requête. Même clé/contenu : `{"ok":true,"duplicate":true}` ; même clé/contenu différent : HTTP 409. **Le doublon ne restitue pas `commandId`/`recordId` du premier retour.**

Commande réellement retournée par GET :

```json
{
  "id":"<32 hex>",
  "createdAt":0.0,
  "body":{
    "version":2,
    "protocol":"machines-v1",
    "guildId":"<ID du serveur du site>",
    "page":"machines",
    "action":"add-machine | recover | unrecover | edit-machine-time | cancel-machine",
    "recordId":"<ID stable de fiche du site>",
    "values":{},
    "actor":{"id":"<ID Discord permanent>","name":"<nom du profil au clic>"},
    "record":null
  }
}
```

`values` vaut `{"amount":<entier>}` pour lancement, `{"launchTime":"HH:MM"}` pour édition, `{}` sinon. `record` est null pour lancement ; pour modification, c’est la fiche résultante **déjà confirmée avant la demande**, telle que stockée au moment de mise en file, et non une preuve de l’exécution souhaitée. `createdAt` est un nombre de secondes Unix, pas une date ISO.

GET renvoie au plus 50 commandes, triées `created,id`, uniquement celles jointes à `bot_machine_jobs`, de statut `pending` et `acknowledged IS NULL`. Si le drapeau métier est désactivé : tableau vide, après authentification HMAC. **Il n’existe pas de cutoff temporel d’activation.** L’exclusion des anciennes commandes repose sur la jointure avec la nouvelle table de jobs ; les anciennes lignes sans job ne sont jamais livrées. `enqueue` générique est désormais un no-op : les actions Sale/Tombola conservent leur parcours local et ne sont pas mises en file.

## 3. ACK : quatre états, terminalité et contraintes

Source : `bot_bridge.py:128`.

Corps :

```json
{
  "guildId":"<serveur du site>",
  "commandId":"<32 hex>",
  "status":"pending | applied | failed | uncertain",
  "result":{"machine":{}},
  "error":{"code":"<texte>","message":"<texte>"}
}
```

- `guildId` chaîne égale au serveur configuré ; ID de commande `[a-f0-9]{32}` ; absence du job Machines HTTP 404, y compris une ancienne commande sans job.
- `status` absent vaut `applied`.
- `result` doit être un objet après normalisation ; le code utilise `payload.get('result') or {}`, donc les valeurs JSON fausses vides sont ramenées à `{}` avant le contrôle de type.
- Pour tout état autre que `applied`, `error` obligatoire : objet contenant uniquement `code`, `message`, tous deux chaînes de longueur 1..500.
- `pending` conserve `acknowledged == NULL`, met à jour l’erreur visible, reste livré par GET. Il représente une reprise contrôlée encore possible.
- `applied` : si `result.machine` fourni, applique la validation et synchronisation canonique dans la même transaction. Ensuite une correspondance `bot_machine_links` doit exister pour la fiche du job, sinon HTTP 409.
- `applied`, `failed`, `uncertain` fixent `acknowledged`, deviennent terminaux et disparaissent de GET.
- Redélivrer le même ACK terminal avec le même `status` renvoie `{"ok":true,"duplicate":true,"status":...}`. Changer son statut ensuite donne HTTP 409. **Le serveur compare le statut, pas l’égalité du résultat ou de l’erreur.**

Le site n’exige pas, à lui seul, une nouvelle révision confirmant la modification avant un ACK `applied` sans `result.machine` : un lien préexistant suffit. Le client de bot présent fournit normalement le résultat complet, mais cette propriété du serveur doit être connue par un autre intégrateur.

## 4. Événements réellement acceptés

Source : `bot_bridge.py:157`.

Enveloppe commune : objet avec `guildId` chaîne égale au serveur configuré, `eventId` correspondant à `[A-Za-z0-9_-]{16,100}`, `kind`.

| `kind` | Champs et effet |
|---|---|
| `heartbeat` | Aucun champ métier requis. Actualise la présence du connecteur. |
| `ready`, `roles_update` | Invalide le contrôle des rôles et des membres Discord en cache, pas les profils invités. |
| `member_update` | `userId` chaîne `[0-9]{1,24}` ; invalide le contrôle de cet utilisateur. |
| `member_remove` | Même ID ; marque non membre et supprime ses sessions site. |
| `machine_sync` | `machine` canonique obligatoire ; `commandId` optionnel au niveau enveloppe ou dans `machine`. Aucun lancement Discord effectué par ce traitement. |
| `action` | Parcours métier générique entrant toujours présent pour Sale/Tombola, avec validation `domain.ACTIONS`, auteur et valeurs. **Page Machines explicitement refusée**, HTTP 400 : elle exige `machine_sync`. |

Pour `action` uniquement : `page`/`action` doivent appartenir à `domain.ACTIONS` (sauf Machines), `values` doit être un objet, `recordId` facultatif doit être une chaîne ; `actor` objet avec `name` chaîne 1..100 et ID dont la conversion en chaîne correspond à `[0-9]{1,24}`. Le serveur appelle ensuite `domain.mutate` avec cet auteur ; aucune nouvelle commande ne repart vers le bot. Cela ne signifie pas qu’un consommateur Sale/Tombola existe dans le bot.

Événements inconnus : HTTP 400. Leur fingerprint est `sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode())`, donc `ensure_ascii=True` implicite ; cela est distinct de la signature HTTP. Même ID/contenu canonique : résultat précédent + `duplicate:true`, sans réappliquer. Même ID/autre contenu : HTTP 409. Pas de purge de `bot_inbox` dans ce code.

Une première application réussie enregistre `bot_last_seen={at:<secondes Unix>,kind:...}`. **Le retour anticipé d’un événement déjà reçu n’actualise pas cette présence.** Le heartbeat doit donc employer un nouvel `eventId`, contrairement aux retries métier qui gardent le même ID.

## 5. Schéma et validation exacts de `machine_sync.machine`

Source : `bot_bridge.py:205`.

| Champ | Validation réellement faite |
|---|---|
| `machineId` | Chaîne `[A-Za-z0-9:_-]{1,160}`. |
| `guildId` | Égalité exacte à la chaîne du serveur du site. |
| `actor` | Objet ; `id` chaîne `[0-9]{1,24}` ; `name` chaîne longueur 1..100. Champs supplémentaires non refusés. Pas de vérification Discord directe dans cet endpoint signé. |
| `amount` | `type(value) is int`, donc booléens refusés, borne 1..1 000 000. |
| `revision` | Entier strict, 0..`2**63-1`. Les sauts de révision sont acceptés. |
| `recovered`, `cancelled` | Deux booléens stricts obligatoires. |
| `launchedAt`, `finishAt` | Chaînes de longueur ≤ 80, acceptées par `datetime.fromisoformat` après remplacement `Z` → `+00:00`, avec fuseau ; timestamp Unix converti en millisecondes par `int(timestamp*1000)`, ≥ 0. Ce n’est pas une validation RFC3339 stricte. |
| Durée | Différence des deux timestamps millisecondes exactement `285*60000`. |
| `recoveredAt`, `cancelledAt` | Facultatifs/null ; même validation de date que ci-dessus. |
| `recoveredBy`, `cancelledBy` | Facultatifs/null ; objet avec `name` chaîne 1..100, `id` facultatif/null ou chaîne `[0-9]{1,24}`. |
| `storage` | Objet facultatif, défaut `{}` ; seules clés `sheetId`, `worksheet`, `row`, `localRef`, `warning`. Les champs textuels présents non nulls : chaînes 1..300. `row` présent non null : entier strict ≥ 1. |
| `messages` | Objet facultatif, défaut `{}` ; seules clés `channelId`, `launchMessageId`, `finishMessageId`, `messageIds`. Les trois références unitaires, si non nulles, doivent satisfaire `[0-9]{1,24}` après conversion `str`. `messageIds` : liste ≤ 1 000 éléments, chacun vérifié de même. Employer des chaînes pour conserver les grands IDs dans JavaScript. Une chaîne vide est invalide ; omettre ou envoyer null pour une référence absente. |
| Taille refs | `len(json.dumps([storage,messages])) <= 16000`. Ce contrôle compte les caractères sérialisés Python, pas les octets du corps HTTP. |
| `siteRecordId` | Facultatif ; une fois résolu : chaîne `[A-Za-z0-9_-]{1,100}`. |
| `commandId` | Facultatif au niveau enveloppe ou dans `machine` ; si présent : `[a-f0-9]{32}` et job existant. Le job impose son `site_record_id`. |

Pas de rejet général des clés supplémentaires de `machine`. Le fingerprint de révision conserve ces clés supplémentaires. Pas d’exigence que `recoveredBy/At` soit présent lorsque `recovered` est vrai, pas de contrôle de cohérence des dates de récupération/annulation avec le lancement, pas de règle imposant `cancelled => recovered`. L’endpoint fait confiance au bot authentifié pour ces cohérences.

Résolution de la correspondance : job par `commandId` si fourni ; sinon lien existant ; sinon `siteRecordId` explicite ; sinon `bot-` + 24 premiers caractères du SHA256 de `guildId + ':' + machineId`. Un lien existant ne peut pas changer de fiche. Une fiche ne peut pas être reliée à deux machines. Une fiche préexistante sans correspondance fiable `botMachineId` provoque HTTP 409 plutôt qu’une fusion arbitraire.

Le snapshot canonique enregistré pour la révision est le JSON trié du `machine` reçu, **sauf `siteRecordId` et `commandId`**. Révision inférieure : réponse `stale:true`, pas de retour en arrière. Même révision/même snapshot : `unchanged:true`. Même révision/autre snapshot : HTTP 409. Les validations de forme sont faites avant ces décisions.

Projection durable de la machine dans `domain_store` :

- `id` = ID du site ; `botMachineId`, `guildId`, `botStatus='confirmed'`, `botRevision`.
- `actorId`, `launchedBy`, `amount`, `start` en millisecondes, `finishAt` en millisecondes.
- `recovered`, `cancelled`, auteurs et dates associés ; suppressions des métadonnées absentes dans un nouveau snapshot.
- `machineCount=5`, `nominalUnitAmount=200000` sont des métadonnées d’affichage ; le montant n’est pas multiplié et le compteur prend une unité par fiche.
- `storage`, `messages`, `historical=False`, `trackingDisabled=False`.
- `machineBridgeConfirmedOnly=True` au niveau état.

À révision supérieure, le serveur autorise la mise à jour de l’auteur, du montant et des horaires d’une fiche déjà reliée ; il n’impose pas leur immutabilité. Les invariants métier de ces champs sont donc assurés par les fonctions du bot émetteur.

L’événement ne met jamais de commande métier en file : pas de boucle de synchronisation.

## 6. Affichage, données anciennes et compteurs

Sources : `app.py:398`, `views.py:60`, `domain.py:74`, `static/app.js:119`, `static/secure.js:385`.

En mode connecté, les lectures Machines/Overview/Stats marquent les anciennes fiches sans `botMachineId` `botStatus='unconfirmed', historical=True, trackingDisabled=True` **dans une projection de lecture**, sans les supprimer ni les rejouer. Elles restent visibles dans l’historique et sont exclues du lot courant. La synthèse des lots récupérés et le classement courant excluent les fiches non confirmées.

Le classement courant est dérivé des machines confirmées non annulées, par ID permanent de l’auteur, dont la date de lancement à Bruxelles est ≥ lundi courant. Un lot = une unité. Cela n’est pas une copie du fichier de compteurs du bot : les resets manuels de compteurs Discord et les classements archivés du bot ne sont pas synchronisés par ce seul événement. Les vieux rapports `machineStats.history` présents sur le site restent un mécanisme séparé.

`machine_status()` renvoie :

```text
botConnection: { enabled, online, lastSeen }
machineCommands: [{ id, createdAt, action, recordId, actor, status, error }, ...]
```

Les 50 derniers jobs sont affichés, tous utilisateurs confondus pour les personnes autorisées à cette page. `enabled` signifie drapeau + secret configurés ; `online` signifie en plus dernier événement accepté depuis moins de 90 secondes. Cela ne garantit pas, à lui seul, qu’une opération est réalisable dans Discord.

UI : en attente du bot / confirmée / échec / échec partiel. Elle n’affiche pas une simple sauvegarde locale comme une confirmation Discord. Le bouton de lancement est bloqué si lot actif, lancement `pending`/`uncertain`, ou liaison désactivée. **L’absence de heartbeat récent n’interdit pas de mettre une demande en attente.** L’interface conserve en revanche un verrou de récupération avant la fin des 4 h 45, même si le bot et la nouvelle file acceptent une récupération anticipée : cette différence entre UI et API demeure (`app.js:52`).

Actualisation : timer toutes les 15 s, lecture effective au plus toutes les 15 s si job pending, sinon 30 s. Uniquement sur la page Machines visible, avec session, sans formulaire ouvert, sans champ en cours d’édition ni action/lecture déjà active. Pas de websocket ni de push navigateur ; une reconnexion/navigation ou le bouton Actualiser récupère aussi les confirmations.

## 7. Budget, erreurs et supervision

`traffic.py:43` : les trois chemins du connecteur ont un compartiment `connector:<adresse ASGI>` avec le quota `connector-minute` fondé sur `visitor_per_minute` (défaut du code : 180/min). Le quota d’écriture navigateur de 30/min n’est pas consommé par ces trois chemins. Les requêtes invalides ou non signées sont comptées aussi. Adresse issue de `scope.client`, pas de confiance directe dans `X-Forwarded-For` dans ce middleware. Si le frontal fait arriver toutes les requêtes avec la même adresse, elles partagent ce quota connecteur.

Le compteur SQLite réservé fonctionne par fenêtres fixes de 60 s ; tickets réservés par blocs de huit, partageables entre processus sans dépasser le plafond, avec possibilité de perdre des tickets inutilisés sur arrêt. Dépassement : HTTP 429, `Retry-After`, JSON `reason='visitor_rate_limited'`, `retryAfter` secondes, pas de corps métier confirmé. Un import initial de nombreuses fiches peut nécessiter plusieurs fenêtres.

Les quotas sortants Discord et Google sont séparés (défauts du code : Discord 120/min et 10 000/j, Google 30/min et 500/j), et ne constituent pas un budget dédié au bot Discord externe. Le code de la queue/synchronisation signé n’effectue pas lui-même de requête à Discord/Sheets.

`GET /api/admin/bot-connection` est réservé à l’administrateur suprême et expose configuration booléenne, dernier événement et nombre `bot_commands.acknowledged IS NULL`. Ce nombre inclut **les anciennes lignes non jointes à des jobs et non livrables**, pas seulement les jobs actifs ; ce n’est donc pas un compteur exact des commandes Machines à traiter (`app.py:690`).

## 8. Limites et écarts à conserver dans le handoff

1. **Confirmation serveur permissive** : un ACK `applied` vide pour une modification peut réussir avec un lien de lancement déjà existant, sans nouvelle révision prouvant cette modification (`bot_bridge.py:144`). L’intégrateur doit envoyer le résultat canonique complet ; le serveur ne l’impose pas dans tous les cas.
2. **`uncertain` terminal sans API de résolution** : `acknowledged` est fixé ; changement ultérieur vers `applied` est refusé ; le job incertain continue à bloquer de nouveaux lancements/modifications. Il n’existe pas de route pour rouvrir/résoudre ce job. Une résolution du journal du bot n’efface pas automatiquement ces états de queue (`bot_bridge.py:85`, `:141`, `:150`).
3. **Reset de test sans remise à zéro des liens** : `POST /api/admin/reset-test-data` remplace `domain_store` mais ne supprime pas `bot_machine_links`, `bot_inbox`, jobs et correspondances côté bot (`app.py:700`). Rejouer le même événement est dédupliqué ; envoyer le même snapshot/révision renvoie `unchanged` avant de reconstruire la fiche. Ce reset peut donc laisser le site vide pour des machines toujours reliées. Ne pas l’utiliser comme outil de migration du raccordement.
4. **Compteur financier encore mixte** : `domain.allocations` utilise toutes les machines récupérées non annulées sans filtrer `botStatus` (`domain.py:27`). Les projections d’affichage marquent les vieux essais comme non confirmés, mais `financial()` appelle toujours cette fonction ; de vieux essais récupérés peuvent donc influencer les sommes Sales/Overview/Stats. La synthèse Machines et le classement courant ont, eux, le filtre de confirmation. Le raccordement Sale n’est pas effectué par cette version.
5. **`WebsiteClient.poll` n’est pas le consommateur métier fourni** : helper générique qui appelle `handler`, puis ACK `applied` sans résultat dès qu’il retourne normalement (`website_client.py:68`). Il ne comprend pas les retours de statut métier, contrairement au `MachineWebsiteBridge` du bot. Ne pas l’utiliser à la place du gestionnaire durable sans adaptation.
6. **Les états HMAC ne sont pas des autorisations utilisateurs** : le serveur interne fait confiance à l’émetteur possédant le secret pour les snapshots. Le contrôle du membre et des rôles d’exécution relève du bot. La connexion OAuth et l’accès à la page seuls ne garantissent pas ce droit d’exécution.
7. **Pas de migration automatique des essais**, pas de suppression historique, pas de mise à niveau des anciens IDs de fiche en machines réelles. Pas de preuve d’exécution réelle sur Discord dans cet audit.

## 9. Ce que le bot actuel émet réellement

Le moteur appelle `MachineWebsiteBridge`, pas le helper générique `WebsiteClient.poll`.
Les événements métier sont des snapshots complets `kind=machine_sync`, même pour
une récupération, une correction d’heure ou une annulation. Il n’existe pas de
nouveau type `machine_recovered` ou `machine_cancelled` à inventer côté site.

Le bot actuel **n’ajoute pas `commandId` au snapshot émis par `_send`** :
`BridgeStore.snapshot` le retire. Pour une commande site, la corrélation est
assurée par `siteRecordId`, l’`eventId=machine-command-<commandId>` et l’ACK
qui contient explicitement `commandId`. Le serveur accepte aussi un `commandId`
optionnel dans l’événement, mais il ne faut pas le rendre obligatoire sans
modifier également le bot. Cela corrige une formulation trop impérative du
précédent guide du site.

Pour une projection issue de Discord, l’ID d’événement est `machine-sync-` suivi
du SHA256 hexadécimal de `json.dumps(machine, ensure_ascii=False, sort_keys=True,
separators=(',', ':'))`. Garder cet ID et le contenu exact lors d’une relivraison.
Pour les heartbeats et notifications d’accès, le client crée un nouvel UUID hex
à chaque nouvel événement. Les notifications d’accès sont best effort, sans
outbox de reprise ; les snapshots Machines disposent d’une persistance.

`MachineWebsiteBridge.run` attend Discord prêt, traite les commandes puis la
projection passive toutes les 10 secondes environ. Heartbeat au moins toutes
les 30 secondes tant que les appels précédents aboutissent ; ce n’est pas un
échéancier indépendant des délais réseau. Le backfill prend au maximum 20
snapshots par tour, les lignes SQLite les plus récemment insérées d’abord.
Les codes HTTP 400/409/422 d’une projection sont journalisés et isolés ; les
snapshots refusés restent en attente. La projection ne crée aucune commande.

## 10. Exemples complets à transmettre

Toutes les valeurs de `exemples/` sont fictives. Les fichiers sont des **corps JSON**,
pas des requêtes authentifiées prêtes à envoyer en production. Aucun secret,
cookie, jeton ou en-tête de signature réel n’est inclus. Les noms d’en-têtes et la
formule de signature sont décrits ci-dessus.

| Fichiers | Séquence |
|---|---|
| `01` à `03` | POST navigateur authentifié → réponse HTTP 200 pending → GET signé des commandes. |
| `04` à `07` | Snapshot confirmé du lancement → ACK applied → réponses du site. |
| `08` | Lancement Discord, sans commande site, projection canonique. |
| `09` à `11` | Commande de récupération, snapshot et ACK ; le lanceur A reste `actor`, l’opérateur B est `recoveredBy`. |
| `12` à `14` | Annulation alternative du même état initial ; `cancelled=true` et `recovered=true` comme le moteur, exclue des montants récupérés. |
| `15` à `17` | Échec définitif, reprise contrôlée pending, résultat de stockage incertain terminal. |
| `18` et `19` | Correction d’heure et retour en non récupérée. |
| `20` | Heartbeat. |
| `21` | Corps d’erreur HTTP 409 ; différent d’un ACK métier failed. |

La récupération et l’annulation des exemples sont des scénarios alternatifs,
pas une obligation d’annuler une machine déjà récupérée. Les révisions illustrent
une progression, sans imposer les numéros exacts d’une session réelle : des mises
à jour de références de rappels peuvent aussi augmenter la révision.

Le `createdAt` des commandes et les métadonnées de présence sont en secondes Unix.
Les snapshots transportent les horaires en chaînes ISO avec décalage ; le site
les projette en millisecondes Unix dans `start`, `finishAt`, `recoveredAt` et
`cancelledAt`. Un nom `finishAt` identique ne signifie donc pas le même type
entre le transport signé et l’état de la page. Les identifiants Discord doivent
rester des chaînes côté JavaScript.
