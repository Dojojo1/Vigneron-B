# Audit du site L’Héritage — 10 novembre 2026

## Périmètre et méthode

Le Site GitHub `Vigneron-B` était propre sur `main` (`5d71c18`) avant les changements. Les tests et mesures ont utilisé des serveurs locaux, des bases temporaires et des avatars simulés. Le Site Linux et le bot vivants ont ensuite été contrôlés en SSH, avec des lectures SQLite en mode `ro`. Aucun message Discord ni aucune modification Google n’a été déclenché. Aucune source, donnée ou configuration Linux n’a été modifiée.

L’audit « impeccable » donne **12/20 avant** et **14/20 après** les corrections ciblées : accessibilité 2/4, performance 2→3/4, responsive 3/4, thèmes 3/4, intégrité 2→3/4. Le contrôle de largeur n’a relevé aucun débordement horizontal entre 320 et 1 440 px sur les pages examinées. La direction artistique, les images et les animations ont été conservées.

## Constats classés par impact

| Impact | Constat et preuve | État |
| --- | --- | --- |
| Élevé | [secure.js](../static/secure.js), anciennement lignes 94–101 et 160 : l’API attendait tous les avatars avant de rendre Équipe. Sur 20 avatars simulés avec 1 s de latence chacun, l’écran apparaissait à **4 850 ms** et le navigateur ouvrait jusqu’à **6** téléchargements simultanés. | Corrigé : écran à **770 ms**, 4 téléchargements simultanés maximum ; les 20 photos sont visibles à **6 895 ms** avec les initiales pendant l’attente. Les URL d’objet sont révoquées à la sortie de session. |
| Élevé | [demo.js](../static/demo.js) renvoyait un tableau pour l’export, mais [app.js](../static/app.js) attend `events` et `saleRefs` : clic CSV en échec. | Corrigé et vérifié par clic navigateur avec capture du CSV. |
| Élevé | En l’absence de jeton, [secure.js](../static/secure.js) tentait `/api/me` avant de présenter l’entrée GitHub connectée ; un backend indisponible empêchait le bouton de connexion. | Corrigé : l’accueil utilise directement la configuration publique déjà chargée. Le test navigateur vérifie qu’aucune page privée ne s’ouvre avant connexion. |
| Moyen | [demo.js](../static/demo.js) utilisait `location.replace('#council')`. Sous le `<base>` de GitHub Pages, cela ouvrait `/static/#council` et renvoyait 404. | Corrigé par navigation de fragment sur l’URL courante. |
| Moyen | [secure.js](../static/secure.js), lignes 622–655 environ : un suivi métier interroge la page toutes les 2 s, pendant que l’actualisation automatique la relit toutes les 3 s lorsqu’une commande est en attente. | À reprendre avec une mesure réseau sur le site connecté et un contrôleur de suivi unique ; risque de modifier les états visibles pendant l’attente. |
| Moyen | [security.py](../backend/security.py), lignes 152–170 : un verrou partagé couvre des appels Discord réseau. [app.py](../backend/app.py), middleware vers ligne 176 et route vers ligne 545 : la permission de page est lue deux fois. Le chemin d’une page privée peut ouvrir environ **16 connexions SQLite**. | À profiler sur une copie isolée avec un fournisseur Discord simulé ; préserver la double lecture de session qui protège la révocation. |
| Moyen | [bot_bridge.py](../backend/bot_bridge.py), ligne 120, et [business_bridge.py](../backend/business_bridge.py), ligne 93, trient les commandes par `created` sans index dédié dans le schéma. Le plan SQL Linux montre un scan et un arbre temporaire pour le tri, mais la table ne contient actuellement que **63 commandes**. | Index à envisager si l’historique ou la latence croît ; aucune migration de la base réelle lancée. |
| Moyen | [website_client.py](../connectors/website_client.py), lignes 73–83 : le helper `poll` envoie un ACK sans résultat, incompatible avec `result.machine` ou `result.snapshot`. Aucun appel à cette méthode n’a été trouvé dans le bot Linux vivant, qui utilise son propre orchestrateur. | Dette de contrat, sans preuve d’incident déployé ; corriger avant tout usage de ce helper. |
| Moyen | [business_bridge.py](../backend/business_bridge.py), ligne 269 : `confirm-sales-reset` accepte un ACK appliqué sans vérifier dans le snapshot que la semaine a changé. | Ajouter un test contractuel et comparer au bot vivant avant modification. |
| Moyen | [secure.js](../static/secure.js) dépasse 800 lignes, [app.js](../static/app.js) dépasse 500 lignes, [app.py](../backend/app.py) approche 900 lignes, et le `bot.py` Linux compte **6 060 lignes**. Navigation, accès, rendu et transport restent fortement couplés. | Décomposition progressive recommandée ; pas de refonte structurelle sans tests d’équivalence sur les deux sites. |
| Moyen | [index.html](../static/index.html), ligne 71 : `aria-live="polite"` entoure tout le contenu, y compris un compte à rebours actualisé chaque seconde. À 320 px, le bouton du menu mesure 30×30 px et celui des réglages 28×28 px. | Audit lecteur d’écran et correction ciblée d’accessibilité à prévoir ; aucun redesign entrepris. |

## Mesures de chargement et d’animation

Sur Chromium avec cache désactivé, fixture locale et même page d’accueil :

| Mesure | Avant | Après |
| --- | ---: | ---: |
| Premier contenu (FCP) | 576 ms | 536 ms |
| Plus grand contenu (LCP) | 704 ms | 536 ms |
| Décalage cumulé (CLS) | 0,00019 | 0 |
| Événement `load` | 733 ms | 648 ms |
| Ressources | 54 | 53 |
| Octets transférés | 1 655 712 | 1 657 759 |

Ces deux chargements uniques varient avec l’ordonnancement local ; ils ne démontrent pas un gain général de 85 ms. Les deux images visibles les plus lourdes représentent ensemble environ **1,07 Mo** et n’ont pas été modifiées. Le gain démontré concerne la disponibilité de l’écran Équipe avec avatars retardés.

GSAP est chargé par [index.html](../static/index.html) et utilisé dans [heritage-motion.js](../static/heritage-motion.js). Les 22 gouttes observées utilisent transformation et opacité ; leurs boucles se mettent en pause hors écran ou en mode léger. Sur 2 s, Chromium a mesuré 27 ms de script et 95 ms de recalcul de style en mode normal, contre 6 ms et 35 ms en mode léger. Comme le mode léger modifie aussi le CSS, cet écart ne peut pas être attribué à GSAP seul. Aucune animation n’a été supprimée ou retouchée.

## Chargement backend et tests

L’assertion de [verify_load.py](../scripts/verify_load.py), ligne 97, attendait encore 10 lots alors que [views.py](../backend/views.py), ligne 99, en précharge 5. Le test a été aligné et vérifie désormais aussi le total de 1 000 lots. Sur la fixture temporaire (1 000 dossiers, 1 000 lots, 10 000 entrées d’audit, concurrence 10), il a traité **154 requêtes en 5,306 s**. Latences p95 : bootstrap **648 ms**, pages **659 ms**. Ces chiffres ne représentent pas les données Linux réelles.

Vérifications passées : 42 tests Python ciblés, 4 tests du filtre sur GitHub, `node tests/browser_pages.mjs`, `node tests/browser_resume.mjs` avec `PYTHON_BINARY=python`, `node tests/local_business.mjs`, `node tests/site_connection.mjs`, `python scripts/verify_load.py`, vérifications syntaxiques JavaScript, `git diff --check` et détecteur « impeccable » (`[]`). Le premier essai de `browser_resume.mjs` a échoué uniquement parce que son chemin `.venv-check` par défaut n’existe pas sur ce poste. Le Site Linux n’a pas encore `tests/test_sale_refs.py` ; la projection du filtre a donc été évaluée directement en lecture seule sur sa base actuelle.

## Copies et déploiement

La comparaison des sources texte `backend/`, `static/` et `connectors/` avec le **Site Linux vivant** (fins de ligne normalisées) donne **29 fichiers identiques, 23 différents et 21 présents seulement dans le Site GitHub**. Le Linux est sur `24688ac`, derrière `origin/main` de sept commits, avec de nombreuses modifications locales. Il ne contient notamment pas le GSAP et les effets associés du Site GitHub ; la revue GSAP concerne donc cette dernière copie. Le Site Linux sert l’API réelle, et sa copie de l’interface ne doit pas être remplacée en bloc par celle de GitHub.

Le Site Linux et `blanchimentbot.service` sont actifs depuis le **10 novembre 2026 à 11:03:39 CET**. Le heartbeat enregistré dans la base du site avait **15,6 s** lors du contrôle. La base du site contient **42 dossiers, 197 machines, 62 758 entrées d’audit, 63 commandes et 28 657 événements reçus du bot**, pour environ 31,4 Mo. Les 29 commandes Machines sont appliquées ; côté métier, 32 sont appliquées et 2 portent un échec enregistré. Ces statuts ne prouvent pas une panne actuelle.

Le bot Linux charge **198 rappels** depuis un JSON de **176 755 octets**. Une analyse JSON pure mesurée 50 fois coûte en moyenne **2,3 ms**. Dans `bot_website_bridge.py:302–318`, le cycle relit ces rappels et examine les snapshots ; `bot_website_bridge.py:87–110` ouvre une transaction par machine. Le coût complet de ce cycle, incluant SQLite et réseau, n’a pas été mesuré : aucun envoi au site ou à Discord n’a été provoqué pour le profiler.

Le correctif GitHub du filtre « En cours » est `5d71c18`, daté du **9 novembre 2026 à 21:13:53 CET**, dans [views.py](../backend/views.py), lignes 66–69. Le fichier Linux correspondant contient la même condition et a été modifié le **9 novembre à 21:13:37 CET** ; `sale_refs.py` y a été modifié à **21:13:41 CET**. `heritage-site.service` utilise ce dossier comme répertoire de travail et a démarré le **10 novembre à 11:03:39 CET**. **Le service a donc été redémarré après le correctif.** Sur les données actuelles, un ancien dossier annulé existe et aucun ancien dossier annulé n’apparaît parmi les deux dossiers affichés dans « En cours ».

Les six fichiers source/test modifiés et ce rapport restent locaux. La publication GitHub Pages reste à effectuer après revue du diff. Toute mise à jour du Site Linux doit être préparée séparément à partir de son état local actuel ; le bot Linux n’a pas été modifié.
