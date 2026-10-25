# Préchargement des espaces — 24 octobre 2026

> Document historique : depuis le 25 octobre 2026, la dernière version est uniquement dans `site/`. Démarrage : `./lancer-site.sh` depuis la racine du projet. Les anciens noms de dossiers ci-dessous décrivent la situation au moment du contrôle.

Modification activée uniquement dans `preview-discord/`, sur **http://127.0.0.1:8081**. Le design, le site historique et le bot ne sont pas modifiés.

## Fonctionnement

1. Au démarrage, `/api/me` confirme le compte et sa navigation autorisée.
2. Un seul `/api/bootstrap` charge ensemble les vues de départ de ces espaces. Il utilise les mêmes projections que les anciennes routes d’écran et décode les collections métier utiles en une lecture groupée.
3. Les changements de section affichent les données déjà en mémoire, sans attendre une réponse HTTP. Les visites réelles sont enregistrées séparément, en arrière-plan, avec un log durable `page_view` par navigation.
4. Une opération invalide les vues concernées, y compris leurs filtres, puis lance un bootstrap ciblé. Les pages sans lien avec l’opération restent disponibles immédiatement. Un rafraîchissement toutes les 60 secondes récupère aussi les modifications externes.

Les premières listes restent paginées : 50 lignes par défaut, 20 événements pour les ventes. Les recherches, pages suivantes, anciennes semaines et classements sont chargés à leur sélection puis conservés sous leur propre clé en mémoire. Les détails des logs, le catalogue des véhicules, les lignes Sheets et les exports restent demandés explicitement. La totalité du journal permanent et des archives n’est donc pas téléchargée à chaque ouverture. Le Conseil conserve sa liste complète de comptes, comme auparavant.

Le cache est limité à 48 entrées et environ 16 Mo de texte JSON. Les vues de départ sont conservées en priorité. Il disparaît à la fermeture/recharge du document ; aucune donnée métier n’est ajoutée au stockage local ou au cache HTTP.

## Droits, erreurs et saisies

- Le backend vérifie les autorisations avant chaque projection du bootstrap, avant les visites et avant toute API ou opération. Les pages interdites ne sont jamais préchargées. Le rôle prioritaire unique, le compte suprême et CSRF restent inchangés.
- Le navigateur contrôle la session toutes les 10 secondes dans un onglet visible. Après 30 secondes sans confirmation, il exige une nouvelle vérification avant restitution. La vérification Discord conserve son cache serveur existant de 30 secondes par défaut : cette navigation en mémoire n’est pas une révocation instantanée par événement.
- Un changement de compte, rôle ou liste de pages autorisées efface le cache. Une vérification indisponible masque les informations privées. Les événements du connecteur conservent leur effet côté serveur ; le connecteur reste séparé du bot actif.
- Après une absence prolongée de l’onglet, le DOM est masqué pendant la confirmation puis rétabli seulement si compte, droits, navigation et génération de données correspondent toujours. Cela conserve les cases non enregistrées du Conseil et la photo/le pseudo en cours de saisie. Une réponse tardive ne réécrit pas une autre page.
- Un bootstrap malformé échoue immédiatement ; une identité correctement formée mais incohérente autorise une seule resynchronisation. Une panne au démarrage masque le domaine et propose « Réessayer ». Les écritures métier ne sont pas rejouées automatiquement.
- Les visites restent soumises au plafond global de requêtes ; elles ne consomment pas les 30 envois métier par minute. Un préchargement ne produit aucune fausse visite des dix pages.

L’ajout d’un dossier et le reset hebdomadaire remettent également la recherche et les offsets des ventes à zéro, afin que les nouveaux dossiers soient visibles dans la semaine courante.

## Vérifications exécutées

- **251 tests Python réussis**, dont 14 nouveaux cas : défaut de session, pages interdites, rôle prioritaire, révocation, indisponibilité Discord, absence de fuite de collections, égalité des DTO/versions, pagination, absence de fausses visites, CSRF et quotas.
- `tests/browser_preload.py` : dix espaces préchargés ; navigation sans GET de données ni indicateur, même avec des logs retardés de 1,2 seconde ; mutation unique malgré double soumission ; rafraîchissement partiel et périodique ; retrait des accès et de la session ; brouillons profil et Conseil conservés après absence d’onglet.
- `tests/browser_frontend.py` : fumée, erreurs initiales et reprise, métadonnées/identités malformées, resynchronisation bornée, réponses tardives, brouillons, double clic, catalogue et archives à la demande, zéro erreur frontend non gérée.
- `tests/browser_workflows.py` : création/modification/restitution et archivage des ventes, tri récent, grille des accès, photo personnalisée dans Équipe, dix pages sans débordement horizontal à 390 px.

Échantillon Firefox isolé : **4 à 87 ms** par restitution depuis la mémoire, avec zéro requête d’écran ou de bootstrap pendant le parcours des dix sections. Les valeurs dépendent du PC, de la taille des listes et du rendu ; ce ne sont pas des garanties sur tous les navigateurs.

Sur le serveur actif, un contrôle HTTP local a mesuré le bootstrap des dix espaces à environ **48 ms pour 49 Ko**. Le chargement initial doit aussi inclure la session, les scripts, les images et la vidéo ; ce chiffre concerne uniquement la réponse de données groupée.

## Activation et conservation

Sauvegarde préalable : `data/backup-before-preload-1792827144261241402.sqlite3`, permissions `0600`. Le serveur de preview a été redémarré sur 8081. Les empreintes des comptes, rôles, permissions, rôles retenus, sessions, état métier et clés d’opérations sont identiques après redémarrage. Les **764 anciens logs** comparés sont conservés intégralement ; les nouvelles visites continuent de s’ajouter. SQLite : `quick_check = ok`.

La connexion Discord reste temporairement désactivée comme demandé précédemment. Aucun déploiement public, import externe ou message Discord effectué. Les autres limites fonctionnelles du [bilan complet](AUDIT-COMPLET-2026-10-24.md#points-restant-à-décider-ou-à-développer) restent distinctes de cette modification.

```bash
cd /home/dojojo/Documents/bot_blanchiment/site
.venv/bin/python -m pytest -q
.venv/bin/python tests/browser_preload.py
.venv/bin/python tests/browser_frontend.py
.venv/bin/python tests/browser_workflows.py
```

Exécuter les trois parcours Firefox successivement, car ils utilisent le même port Marionette. Ils créent leurs propres serveurs et bases temporaires.
