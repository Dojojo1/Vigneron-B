# Audit après préchargement — 24 octobre 2026

> Document historique : depuis le 25 octobre 2026, la dernière version est uniquement dans `site/`. Démarrage : `./lancer-site.sh` depuis la racine du projet. Les anciens noms de dossiers ci-dessous décrivent la situation au moment du contrôle.

Dernière version contrôlée : `preview-discord/`, serveur FastAPI local sur **127.0.0.1:8081**. Le design choisi est conservé. Les tests d’écriture utilisent des bases temporaires, sans action Discord/Google réelle et sans remplacement des données utilisateur.

**288 tests Python réussis**, dont 37 nouveaux depuis le préchargement. Les contrôles complémentaires et leurs limites sont détaillés ci-dessous ; ce résultat ne démontre pas l’absence de toute faille.

## Problèmes reproduits et corrigés

- Une fenêtre de dossier ouverte restait visible hors de `main` après révocation. Les modales, titres, champs et menus privés sont désormais fermés/purgés sur retrait d’accès ou changement de compte. Une panne conserve le brouillon détaché du DOM, en RAM ; il revient seulement après confirmation du même compte, de la même page et des mêmes droits.
- Une ancienne réponse 503 pouvait effacer les données d’une opération plus récente. Les réponses et erreurs appartenant à une autre génération de données ou d’autorisations sont ignorées. La protection couvre aussi les réponses 200 du catalogue et des archives. Les lectures devenues obsolètes reprennent de façon bornée au lieu de laisser une page vide.
- Changer les paramètres de bootstrap permettait au navigateur de réessayer avant `Retry-After`. Le délai est maintenant commun aux variantes d’un même chemin. Les plafonds serveur restent actifs.
- L’export CSV protégeait les formules directes mais pas toutes celles précédées d’espaces, tabulations ou retours à la ligne. Les préfixes concernés sont neutralisés.
- `to=9999-12-31` faisait planter le journal lors du calcul du jour suivant. La requête est refusée proprement en 400.
- Deux démarrages simultanés pouvaient observer une clé de chiffrement encore vide. La clé est désormais écrite complètement, synchronisée puis publiée atomiquement, sans écraser une clé existante. Une clé invalide n’est jamais remplacée silencieusement.
- Un import JSON fini mais mal typé pouvait casser les écrans, puis le bootstrap global. Classements, noms, catalogue, prix et états Tombola sont maintenant validés avant sauvegarde et remplacement ; un refus conserve la copie existante.
- Les créations et l’archivage global acceptaient des identifiants de fiche incohérents, au risque de modifier ou journaliser la mauvaise cible. Ces identifiants sont refusés.
- Des valeurs JSON `0`/`false` de donneur ou date étaient traitées comme des champs vides. Les types invalides sont refusés ; les noms de véhicule objets, booléens ou nuls ne sont plus convertis en texte.
- Les décodeurs d’image sont limités dès l’ouverture à JPEG, PNG et WebP. Un TIFF déguisé est rejeté sans activer son décodeur. Les photos acceptées restent normalisées en PNG.

Les règles du lot unique de cinq machines, les 285 minutes, les parts 15/80/5, l’archivage, les permissions et les logs permanents sont conservés.

## Dépendances

Les 28 versions du verrou ont été comparées à la base OSV. Les versions précédentes de **Pillow** et **cryptography** étaient signalées. Elles ont été remplacées par **Pillow 13.0.0** et **cryptography 50.0.2**, d’abord dans un environnement temporaire, puis dans la seule preview après tests. Aucun jeton ou clé existant n’a été régénéré.

Après mise à jour, OSV ne renvoie aucune alerte pour les 28 versions contrôlées. Il s’agit des avis connus dans cette base à la date du contrôle, pas d’une garantie sur toutes les dépendances natives, le système ou les vulnérabilités inconnues. Plusieurs identifiants OSV peuvent désigner le même avis : le nombre de lignes d’alerte initial n’est pas présenté comme un nombre de failles distinctes. L’application emploie Fernet ; les avis concernant d’autres fonctions de cryptography ne prouvent pas une exploitation dans cette application.

Sources : [API officielle OSV](https://google.github.io/osv.dev/post-v1-querybatch/), [Pillow 13.0.0](https://github.com/python-pillow/Pillow/releases/tag/13.0.0), [avis cryptography corrigé en 50.0.0](https://github.com/pyca/cryptography/security/advisories/GHSA-g6cj-pr64-35w5). `pip check` contrôle séparément la cohérence des dépendances installées.

## Vérifications

| Contrôle | Résultat |
|---|---|
| Suite Python finale, bases et fournisseurs temporaires | **288 réussis**, 0 échec |
| Connexion simulée, priorité unique des rôles, propriétaire, CSRF, sessions, révocation | Réussis |
| Races de révocation, journaux durables/immuables et quotas interprocessus | Réussis |
| Préchargement, égalité des projections et absence de données de pages interdites | Réussis |
| Données métier et imports ; jeu de 1 200 dossiers | Totaux, FIFO, tri, filtres, refus de types invalides et pagination vérifiés |
| Paiements simultanés avec une même clé | Un seul basculement, achat et paiement indépendants |
| Firefox : préchargement, navigation, profils, photos, rôles, archivage et dix pages à 390 px | Réussis sur bases temporaires |
| Firefox : modales révoquées, brouillons, requêtes concurrentes, réponses anciennes, CSV | Réussis, aucune erreur frontend non gérée dans ce parcours |
| Firefox : pannes 500/503, 429, JSON illisible, réseau, attente de 20 s et reprise | Réussis ; aucune répétition automatique d’écriture |
| Chromium Headless Shell 156.0.8078.47 : dix pages desktop/mobile, menus, modale Tombola, upload et avatar Équipe | Réussis ; zéro erreur JavaScript dans ce parcours |
| Chromium : fondu de la statue et navigation préchargée | Masque alpha en dégradé actif, zéro GET de données et zéro indicateur entre sections |
| Restauration complète depuis copies de la base réelle | Réussie : 1 photo, 2 jetons chiffrés, tables et anciens logs vérifiés ; copies supprimées |
| Secrets privés recherchés dans les ressources publiques | Aucune correspondance parmi les valeurs connues contrôlées, sans afficher les secrets |
| Fichiers privés, ressources statiques et syntaxe | Modes 0600 ; CSS/JS locaux référencés présents ; 60 fichiers Python compilés et 8 fichiers JS parsés |
| Serveur actif et fichiers privés par HTTP | Session/bootstrap répondent ; `.env`, base, clé et sources backend non servis |

L’avertissement de dépréciation Starlette/httpx du client de tests reste présent ; il ne correspond pas à un échec et ne doit pas être confondu avec une analyse des CVE.

## Concurrence et performances

`scripts/verify_load.py` a lancé un serveur HTTP et une base temporaires avec **1 000 dossiers, 1 000 lots et 10 000 logs**. Il a traité **154 requêtes**, avec au plus **10 simultanées** : 141 réponses 200, 12 refus 409 attendus et 1 refus 400 attendu. Aucune réponse 500/503 dans ce parcours.

- 20 répétitions de la même opération : **une seule mutation**.
- 10 lancements concurrents : **un lot accepté, neuf refusés**.
- Récupération prématurée et lancement sans récupération : refusés.
- 30 visites : 30 logs. **146 traces nouvelles attendues, 146 présentes**, y compris après arrêt ; les logs précédents sont conservés.
- Intégrité SQLite finale : `ok`.

Échantillon local sous cette charge : bootstrap médian 637 ms, p95 907 ms ; écritures profil/dossier p95 environ 2,8–3,3 s. Les écritures SQLite restent sérialisées avec confirmation durable ; elles ne doivent pas être assimilées au temps d’un changement de page depuis la mémoire. Ce test borné de dix accès simultanés ne constitue pas une mesure de capacité en production ou une protection contre une saturation réseau prolongée.

Parcours Firefox après corrections : dix sections depuis la mémoire sans GET de données ni indicateur, environ **3–95 ms** dans la dernière mesure isolée. Le chargement initial inclut toujours session, bootstrap et ressources. Les mesures varient avec le disque, la concurrence et le rendu vidéo.

La preview active a aussi été contrôlée en lecture avec Firefox : environ 1,69 s jusqu’au premier affichage et 1,66 s au rechargement ; changements de section de 6 à 103 ms dans ce parcours, sans GET de données ni indicateur. La fumée était en lecture.

Chromium isolé : dix sections préchargées, environ 6–151 ms par navigation dans les deux passages, sans GET de données ni indicateur. Les polices externes étaient bloquées pour isoler le test du réseau. Les premiers essais avaient échoué avant d’ouvrir le site : sandbox du conteneur, puis absence d’onglet initial dans Headless Shell. Le lanceur temporaire ouvre désormais `about:blank` avant pilotage ; le parcours réel a ensuite réussi. Les captures du menu mobile attendent la fin de son animation pour éviter une coupe transitoire. Aucun binaire ni réglage du navigateur personnel n’a été remplacé. Instructions et sorties : [tests/CHROMIUM.md](tests/CHROMIUM.md).

## Activation et conservation des données

Au début du contrôle, le port 8081 était occupé par `python3 -m http.server` lancé depuis l’ancien dossier `site/`. Ses routes `/api/me` et `/api/bootstrap` répondaient 404. Ce serveur statique a été arrêté et remplacé sur 8081 par **`preview-discord/run.sh`**, qui fournit les API de la dernière version.

Une sauvegarde privée précède les changements : `data/backup-before-audit-preload-1792859101129534949.sqlite3`. Après activation, les empreintes des comptes, rôles, permissions, rôles retenus, sessions, document métier et clés d’opérations sont identiques. Les **776 anciens logs** comparés sont conservés intégralement, SQLite répond `ok`, et les nouvelles traces continuent de s’ajouter.

Aucun fichier source du bot ou de l’ancien site n’a été modifié. Le signal généré `site/sales-reset-state.json` continue d’être republié chaque minute par le bot déjà actif : sa variation pendant le contrôle est distincte d’une modification de code ou d’un reset déclenché par cet audit. Aucun message Discord ni import réel n’a été envoyé.

## Limites restantes

- La connexion Discord réelle reste désactivée temporairement comme demandé. Les scénarios OAuth, rôles et erreurs ont été testés avec un fournisseur simulé ; une autorisation réelle complète reste à valider avant mise en ligne.
- Le site et le bot ne disposent pas encore d’une synchronisation métier bidirectionnelle. Le reset automatique reste assuré par le bot, sans worker hebdomadaire équivalent dans cette preview.
- Le recalcul complet des classements archivés après correction et la restriction « ses opérations seulement » ne sont pas activés par cet audit.
- Une restauration locale est testée ; les sauvegardes automatiques hors du PC restent à configurer.
- HTTPS, hébergement public, supervision, protection réseau et coordination des révocations entre plusieurs workers ne sont pas déployés ici.
- Les extensions et réglages propres à Brave/Edge, ainsi que Safari et les appareils physiques, ne sont pas reproduits par les tests automatisés disponibles.
- Pas de test d’intrusion externe ni de charge prolongée sur un hébergement réel ; aucune promesse d’absence de toute faille.

## Relancer les contrôles

Depuis `preview-discord/`, avec Python 3.11 minimum :

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
.venv/bin/python tests/browser_preload.py
.venv/bin/python tests/browser_frontend.py
.venv/bin/python tests/browser_workflows.py
.venv/bin/python tests/browser_failures.py
.venv/bin/python tests/browser_audit.py
.venv/bin/python scripts/verify_load.py
.venv/bin/python scripts/verify_restore.py
.venv/bin/python scripts/audit_dependencies.py
```

Exécuter les parcours Firefox successivement. Le dernier outil nécessite Internet et ne transmet que les noms/versions publics des dépendances ; son échec renvoie « audit incomplet ». Les tests de charge et de restauration utilisent leurs propres dossiers temporaires.
