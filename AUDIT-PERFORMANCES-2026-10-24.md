# Audit des temps de chargement — L’Héritage

> Document historique : depuis le 25 octobre 2026, la dernière version est uniquement dans `site/`. Démarrage : `./lancer-site.sh` depuis la racine du projet. Les anciens noms de dossiers ci-dessous décrivent la situation au moment du contrôle.

Diagnostic du 24 octobre 2026 sur la prévisualisation locale **http://127.0.0.1:8081**. Aucun changement fonctionnel effectué pendant cet audit. Le bot, ses données et les données métier du site restent intacts.

**Mise à jour après l’audit : les corrections prioritaires ont ensuite été autorisées et activées sur 8081.** Les constats ci-dessous décrivent l’état avant correction. Résultat du même parcours Firefox : chargement complet **4,16 → 0,91 s**, rechargement **4,03 → 0,68 s**, retour Blanchiments terminé **environ 0,50 → 0,15 s**, Conseil **0,72 → 0,14 s**. Les quotas visiteurs sont précomptés par blocs durables, les écritures attendues ne bloquent plus la boucle HTTP, les logs concurrents sont regroupés sans réponse avant leur COMMIT, et la navigation utilise un seul appel autorisé. Compteurs fournisseurs exacts, logs permanents et transactions avant/après conservés. 158 tests réussis et parcours navigateur isolé validé ; données métier et anciens logs contrôlés inchangés après redémarrage. Ces temps sont indicatifs d’un parcours local, sans garantie sur tous les navigateurs. Voir les modalités actuelles dans le README.

**Constat principal : le site attend trop souvent que le disque confirme une écriture, même pour afficher une page ou récupérer un fichier CSS.** Les calculs métier actuels sont beaucoup plus rapides que ces attentes. Les images et l’enchaînement des requêtes aggravent ensuite le chargement.

## 1. Mesures dans le navigateur

Parcours automatisé dans Firefox, profil temporaire, fenêtre 1440 × 1000, serveur local actif, Discord désactivé. Ces mesures décrivent cet environnement et ce parcours ; elles ne constituent pas une garantie de temps sur tous les navigateurs.

| Étape | Temps observé |
|---|---:|
| Ouverture initiale, document et ressources du chargement terminés | **4,16 s** |
| Rechargement de la page dans le même navigateur | **4,03 s** |
| Premier affichage de contenu, principalement le chargement | 2,33 s lors de l’ouverture initiale |
| Début du premier appel API au démarrage | **2,32 s après la navigation** |
| Réception des données du tableau de bord | environ 3,47 s après la navigation |

Le premier appel API commence tard : les fichiers nécessaires au démarrage du JavaScript sont eux-mêmes en attente. Des fichiers CSS/JS de quelques kilo-octets ont pris **0,8 à 2,9 secondes** à arriver dans ce parcours. Leur poids seul n’explique pas ces temps.

Temps entre un changement de page et la présence du nouveau contenu, dans un parcours unique après ouverture :

| Page, première visite dans ce parcours | Affichage du contenu |
|---|---:|
| Gestion Blanchiments | 0,62 s |
| Gestion Machines | 0,33 s |
| Statistiques | 0,22 s |
| Équipe | 0,22 s |
| Historique | 0,25 s |
| Véhicule tombola | 0,24 s |
| Mon Registre | 0,23 s |
| Journal | 0,63 s |
| Le Conseil des Accès | 0,72 s |

Sur des retours vers des pages déjà mémorisées : Blanchiments s’affiche après **0,26 s**, mais l’actualisation complète se termine après **0,50–0,52 s** ; Machines s’affiche après **0,40 s**, actualisation terminée après **0,64 s**. Il faut distinguer le retour du contenu et la fin de son actualisation.

Les durées varient entre les essais, notamment avec les accès disque concurrents. Les attentes de plusieurs fichiers se chevauchent : il ne faut pas additionner toutes les lignes de la liste des téléchargements.

## 2. Cause dominante confirmée : les validations sur disque

Le limiteur de requêtes enregistre chaque passage dans une base SQLite. Pour une lecture de page journalisée, le journal permanent réalise une autre écriture avant d’envoyer la réponse.

Une validation durable, appelée `COMMIT`, attend la confirmation du stockage. C’est cette étape qui est lente ici.

Benchmarks sur **des fichiers de test indépendants**, supprimés ensuite, avec les mêmes fonctions que le site — 25 mesures par opération :

| Opération | Fichier temporaire sur le disque du projet, médiane | Même opération dans `/tmp`, en mémoire vive |
|---|---:|---:|
| Enregistrer le compteur d’une requête | **131,82 ms** | 0,64 ms |
| Enregistrer un log | **229,08 ms** | 0,85 ms |

Les maxima observés sur disque atteignent respectivement **525 ms** et **765 ms**. Ce ne sont pas des temps fixes pour chaque requête.

Décomposition complémentaire de 20 petites transactions sur le disque du projet : ouverture de connexion **0,37 ms**, début de transaction et insertion **0,71 ms**, **validation 130,75 ms**, fermeture **0,16 ms**. La lecture d’un utilisateur, connexion comprise, coûte environ **0,61 ms**.

Le projet est sur un système de fichiers ext4 ; `/tmp` utilise la mémoire vive. La différence prouve le coût du stockage dans cet environnement. Elle ne permet pas, à elle seule, d’accuser une panne physique du disque. Le stockage n’est occupé qu’à environ 25 %.

### Pourquoi cela touche même les images

- Le limiteur s’applique à **chaque requête HTTP**, y compris CSS, JavaScript, images, vidéo et réponses de validation du cache.
- Le compteur fait une transaction durable avant de laisser la requête continuer.
- Une lecture de page ou une consultation du journal ajoute généralement une deuxième transaction durable pour le log.
- Ces opérations sont synchrones dans le traitement asynchrone du serveur : pendant leur attente, la boucle principale ne peut pas faire avancer normalement les autres requêtes.
- Le serveur actuel utilise un seul processus de travail. Au démarrage, plusieurs fichiers demandés ensemble s’attendent donc aussi les uns les autres.

La protection ne fait pas volontairement patienter les visiteurs tant qu’ils restent sous le plafond. **C’est la manière de stocker ses compteurs qui entraîne cette attente.**

Sources : `backend/traffic.py:41`, `backend/budget_counter.py:32`, `backend/auditing.py:114`, `backend/storage.py:62`, `run.sh:5`.

## 3. Réponses serveur réelles : peu de données, beaucoup d’attente

Trois lectures successives de chaque route sur le serveur actif, sans téléchargement du décor :

| Réponse | Taille | Temps minimal–maximal des 3 essais |
|---|---:|---:|
| Session et accès (`/api/me`) | 1,64 Ko | 84–105 ms |
| Tableau de bord | 0,69 Ko | 207–260 ms |
| Blanchiments | 4,74 Ko | 265–277 ms |
| Machines | 17,88 Ko | 289–613 ms |
| Statistiques | 1,23 Ko | 278–294 ms |
| Équipe | 0,43 Ko | 301–396 ms |
| Historique | 7,48 Ko | 324–407 ms |
| Préparation du Conseil | **18 octets** | 347–625 ms |
| Rôles et permissions du Conseil | 4,40 Ko | 346–414 ms |
| Comptes du Conseil | 0,40 Ko | 336–744 ms |
| Vérification du droit d’ouvrir Blanchiments | **51 octets** | 116–180 ms |

Les 18 octets du Conseil prennent parfois plus de temps que les 17,88 Ko des machines. Cela confirme qu’ici, réduire encore la taille de ces réponses ne suffirait pas.

Sur une copie isolée de la base réelle dans `/tmp`, avec le même code et les mêmes protections, les médianes de 25 appels sont d’environ **8,3 ms** pour le tableau de bord, **10,2 ms** pour Blanchiments, **10,4 ms** pour Machines et **9,3 ms** pour Statistiques. Aucun appel Discord ni Google métier dans ces tests.

## 4. Démarrage et navigation en plusieurs appels

Le démarrage attend successivement :

1. Les fichiers CSS/JavaScript nécessaires.
2. `/api/status`, pour connaître le mode du site.
3. `/api/me`, pour retrouver le compte et les accès.
4. Les données de la page choisie.

Les trois appels API se suivent : leurs latences s’additionnent. Une partie de cette organisation peut être simplifiée sans charger toutes les données de toutes les pages.

Le Conseil commence par une réponse de préparation de 18 octets, puis lance en parallèle les rôles/permissions et les comptes. Cela impose **deux vagues de requêtes** avant son affichage.

Le cache actuel dure **30 secondes**, uniquement en mémoire de l’onglet. Il est vide après un rechargement et ne couvre pas le Conseil, Mon Registre ni le Journal.

Pour une page mémorisée, il attend une vérification serveur des droits avant de montrer son contenu, puis télécharge à nouveau les données complètes. Le contrôle d’accès reste indispensable. Toutefois, la mise en œuvre actuelle maintient une attente avant l’affichage et augmente le travail total : le contrôle et le rechargement passent tous deux par le compteur, et un retour marqué comme visite peut aussi produire deux écritures de journal, une visite puis une lecture. Cela explique la portée limitée de l’optimisation précédente.

Sources : `static/secure.js:5`, `:158`, `:249`, `:264`, `:337`, `backend/auditing.py:89`.

## 5. Cache des fichiers statiques et compression

Vérifications HTTP :

- Les images sous `/assets/` possèdent un ETag et savent répondre **304**, ce qui permet d’éviter de renvoyer leur contenu si le navigateur les possède déjà. Cette vérification coûte quand même une requête et une écriture du compteur.
- Les CSS/JS ont également un ETag, mais la route actuelle renvoie encore **200 avec le contenu** lors d’un essai avec `If-None-Match` correspondant. La route directe utilise `FileResponse`, sans la validation conditionnelle des fichiers sous `/assets/`.
- Il n’y a pas de durée explicite de conservation `Cache-Control` sur ces fichiers statiques.
- Les réponses observées ne sont pas compressées par gzip/Brotli. Les CSS/JS peuvent donc être allégés en transfert.
- Les API privées et le document `/app` sont `no-store`. Ce choix protège les données privées ; l’optimisation du cache des décors publics ne demande pas de rendre publiques les réponses privées.

Dans l’essai de rechargement Firefox, plusieurs ressources sont reparties sur le réseau. Il ne faut pas en déduire que tous les navigateurs rechargent systématiquement chaque image à chaque clic sur le menu : la navigation interne conserve le document.

Sources : `backend/app.py:128`, `:530`, `:531` ; mesures HTTP conditionnelles.

## 6. Images : un poids nettement réductible

| Image | Dimensions | Poids actuel |
|---|---:|---:|
| Héros du domaine (`midnight-hero.png`) | 2172 × 724 | **2,72 Mo** |
| Statue de la navigation (`midnight-statue.png`) | 887 × 1774 | **1,85 Mo** |
| Illustrations des dossiers (`midnight-dossiers.png`) | 2172 × 724 | **2,51 Mo** |
| Ancienne image des machines (`midnight-machines.png`) | 2172 × 724 | 2,64 Mo |
| Cour du domaine (`welcome-courtyard.png`) | 1672 × 941 | 2,78 Mo |

Le héros et la statue ont été effectivement téléchargés lors de l’ouverture mesurée : **4,57 Mo à eux deux**. L’image des dossiers sert sur les pages qui l’affichent. Les anciens fichiers présents dans le dossier ne sont pas tous chargés à chaque ouverture. L’illustration des dossiers est partagée entre les cartes, elle n’est pas téléchargée à nouveau pour chaque ligne.

Un essai de conversion **en mémoire uniquement**, WebP qualité 85, fait passer héros + statue + dossiers de **7,08 Mo à environ 0,725 Mo**, soit presque **90 % de réduction**. Une vérification visuelle serait nécessaire avant d’adopter cette conversion. Aucun fichier image du site n’a été remplacé.

## 7. Polices et feuilles de style

Le site inclut **7 CSS**, totalisant **147,9 Ko**, et **6 JavaScript**, totalisant **110,3 Ko**. Le poids du code n’est pas gigantesque ; le nombre de requêtes devient néanmoins coûteux avec le compteur actuel. Une estimation gzip donne respectivement environ 38,2 Ko et 36,3 Ko.

`styles.css` importe les polices Cormorant Garamond et DM Sans depuis Google Fonts. Cette feuille distante intervient dans le chargement des styles et peut retarder le démarrage des scripts différés. Dans les essais, la requête Google Fonts a pris environ **0,10–0,33 s** ; un blocage externe pourrait coûter davantage. Ce n’est pas le principal temps perdu mesuré ici.

Les styles successifs contiennent de nombreuses règles qui se remplacent. Leur nettoyage pourrait réduire les requêtes et simplifier le rendu, mais il ne réglerait pas seul les attentes SQLite.

Sources : `static/index.html:7`, `static/styles.css:1`.

## 8. Fumée, animations et rendu

La vidéo choisie normalement par Firefox est le WebM : **229 Ko**, 1280 × 676, 25 images/seconde, boucle de 18 secondes. Le MP4 de secours fait **1,60 Mo**. Le navigateur choisit un format, il ne faut pas additionner automatiquement les deux poids.

La vidéo utilise filtre, masque, transparence et fusion avec le décor. Le site possède aussi une nappe animée plein écran et des effets de flou, notamment sur l’accueil. Cela peut ralentir l’animation ou le défilement sur une machine où le rendu graphique est limité, indépendamment de la vitesse de réponse du serveur.

**La fumée était en pause dans le parcours initial mesuré à environ 4 secondes.** Une reprise de visibilité déclenchée dans le navigateur l’a ensuite mise en lecture, avec chargement du WebM. Elle ne peut donc pas expliquer ces 4 secondes initiales. Son coût graphique dans Brave/Chrome/Edge sur le PC utilisateur n’a pas été quantifié.

Attention aux comparaisons : la préférence « réduire les mouvements » seule ne désactive pas forcément cette vidéo dans le code actuel ; une demande de lecture est active par défaut.

Le code crée également un nouveau formateur de montant/date à chaque utilisation, reconstruit du HTML lors des actualisations et conserve plusieurs minuteries : compteurs à la seconde, historique machines toutes les 10 secondes, horloge et session. La vérification de session fait un appel `/api/me` toutes les **10 secondes** lorsque l’onglet est visible ; chaque appel subit encore l’écriture du compteur.

Dans le parcours mesuré, le temps entre fin de la requête et rendu est généralement de quelques millisecondes à quelques dizaines de millisecondes. Le rendu JavaScript n’explique pas à lui seul les centaines de millisecondes d’attente serveur.

Sources : `static/smoke.js:12`, `:23`, `:29`, `static/theme-finish.css:11`, `static/theme-nuance.css:25`, `static/app.js:6`, `:243`, `:280`, `:304`, `:306`, `static/secure.js:360`.

## 9. Volume des données et index

Lors de la copie de diagnostic : environ **405 Ko de base**, dont **202 Ko de document métier**, avec **94 dossiers**, **100 lots**, **254 événements** et **682 lignes de copie Sheets**. Ce volume est faible.

Les index des comptes, sessions et logs existent déjà. Les calculs des réponses Blanchiments/Machines/Statistiques coûtent moins d’une milliseconde dans les benchmarks isolés ; extraire et décoder les collections JSON prend quelques millisecondes.

La pagination réduit bien les données envoyées au navigateur. Le serveur charge cependant encore l’intégralité de certaines collections nécessaires, puis trie et filtre en Python. Les dossiers et machines sont stockés dans un document JSON unique ; ajouter simplement un index ne rendra pas ces tris Python instantanés.

Ce modèle devra être revu si les volumes atteignent plusieurs dizaines de milliers d’opérations. **La taille actuelle des données n’est pas la cause dominante des lenteurs constatées.**

## 10. Discord, Google et pannes externes

En mode local actuel, aucune vérification Discord n’est effectuée pour naviguer. Les pages consultent la copie des données du bot ; elles ne relisent pas Google Sheets à chaque clic. Ces services n’expliquent donc pas les temps actuels.

Lorsque Discord sera réactivé, d’autres facteurs existent dans le code : vérifications périodiques des rôles/membres, verrou global pendant ces vérifications, nouvelle connexion HTTP à chaque appel, et jusqu’à deux essais pour certains GET avec un délai maximal de 10 secondes par tentative. Une panne pourrait donc produire des attentes beaucoup plus longues, ou faire attendre d’autres utilisateurs. Ces risques n’ont pas été provoqués contre Discord pendant cet audit.

Le frontend possède aussi un délai d’expiration des requêtes : en cas de serveur qui ne répond pas, il peut rester en chargement jusqu’à cette échéance, puis afficher une erreur. Le délai de **180 ms** trouvé dans la navigation n’ajoute aucune pause avant les données : il retarde seulement l’apparition du petit indicateur de chargement.

Sources : `backend/local_preview.py:36`, `backend/security.py:86`, `backend/discord_api.py:40`, `static/secure.js:36`, `:236`.

## 11. Ordre recommandé pour les corrections

| Priorité | Travail | Résultat recherché |
|---|---|---|
| **1** | Revoir le stockage des compteurs et le traitement des écritures bloquantes ; regrouper les opérations lorsque leur fiabilité le permet | Éviter un COMMIT lent pour chaque fichier tout en conservant les plafonds et les logs durables |
| **2** | Corriger le cache des ressources publiques et réduire les vagues de requêtes au démarrage/Conseil/retours mémorisés | Moins d’allers-retours et un contenu disponible plus tôt |
| **3** | Convertir et dimensionner les images, vérifier le rendu visuel | Réduire fortement les téléchargements du décor |
| **4** | Servir les polices localement, regrouper/versionner les ressources stables et activer la compression adaptée | Rendre le démarrage moins dépendant des requêtes multiples et des services externes |
| **5** | Regrouper les minuteries, réutiliser les formateurs, mesurer les effets graphiques sur les navigateurs utilisateur | Améliorer la fluidité après affichage |
| **6** | Préparer un stockage métier mieux adapté à de gros volumes et optimiser les vérifications Discord | Éviter les prochains goulots d’étranglement |

Activer SQLite WAL seul n’est pas une correction démontrée : un essai isolé a amélioré le compteur mais pas le coût du journal avec les connexions courtes actuelles. Déplacer la vraie base dans `/tmp`, désactiver la durabilité ou perdre les logs lors d’un arrêt ne constitue pas une solution acceptable pour les données permanentes.

Les gains exacts après correction devront être mesurés à nouveau. Cet audit identifie et chiffre les causes ; **il ne les corrige pas encore**.

## Méthode et limites

- Code et données source examinés en lecture seule ; les requêtes de consultation produisent leurs logs habituels.
- Lectures HTTP du serveur actif, parcours Firefox sans modification métier, tests de cache conditionnel.
- Microbenchmarks de 20 ou 25 opérations sur des fichiers isolés, en RAM puis dans le dossier de données, avec nettoyage des fichiers temporaires.
- Copies de base temporaires pour les comparaisons, fournisseur Discord factice interdisant les appels réseau.
- Aucune mesure de Brave/Chrome/Edge disponible dans cet environnement. Leurs extensions, caches et conditions graphiques peuvent modifier le résultat.
- Pas de test de charge multi-utilisateur prolongé, pas de diagnostic matériel complet et pas de mise en ligne.
- La charge mémoire/CPU observée ponctuellement ne montrait pas de saturation évidente. Cela n’exclut pas des pointes à d’autres moments.

Scripts de diagnostic conservés temporairement : `/tmp/audit-heritage-browser.py`, `/tmp/audit-heritage-browser.jsonl`, `/tmp/audit-heritage-video.py`, `/tmp/audit-heritage-backend-loading.py`, `/tmp/audit-heritage-backend-loading.out`, `/tmp/audit-heritage-filesystem.py`, `/tmp/audit-heritage-commit-stages.py`.
