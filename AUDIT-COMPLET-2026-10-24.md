# Vérification complète de la dernière preview — 24 octobre 2026

> Document historique : depuis le 25 octobre 2026, la dernière version est uniquement dans `site/`. Démarrage : `./lancer-site.sh` depuis la racine du projet. Les anciens noms de dossiers ci-dessous décrivent la situation au moment du contrôle.

Version contrôlée : `preview-discord/`, servie par FastAPI sur **127.0.0.1:8081**. Les corrections sont activées sur cette preview. Le site historique `site/`, le bot et ses sources de production n’ont pas été modifiés.

**Complément ultérieur :** à la demande du propriétaire, la navigation attend désormais un seul préchargement initial puis affiche les pages depuis la mémoire. Le contrôle HTTP avant chaque restitution décrit dans ce bilan correspond au comportement précédent. Voir [préchargement et vérifications actualisées](PRECHARGEMENT-2026-10-24.md) : 251 tests Python réussis et parcours navigateur adaptés.

**Résultat : 237 tests Python réussis, parcours Firefox complets réussis, restauration locale complète réussie.** Les erreurs confirmées ont été corrigées. Les limites fonctionnelles et de déploiement restantes sont précisées plus bas ; ce contrôle ne garantit pas l’absence de toute faille.

## Reprise après la limite d’utilisation

La limite avait interrompu les trois revues spécialisées et empêché le lancement des tests de restauration. Les fichiers déjà écrits ont été inspectés avant la reprise. Les trois revues ont ensuite été terminées, les tests interrompus ont été exécutés et la suite complète a été relancée après les corrections.

Deux erreurs dans les nouveaux tests ont été corrigées : le contrôle d’identité mettait normalement à jour `checked_at`, et le client de restauration devait présenter une adresse locale pour respecter la protection de la preview. Un test navigateur a également été corrigé pour vérifier le DOM plutôt qu’une variable JavaScript interne inaccessible à l’automatisation.

**Aucune étape prévue dans ce contrôle n’est restée suspendue à cause de la limite.** Les opérations volontairement hors périmètre — connexion réelle Discord, déploiement public et services de production — restent distinguées des tests terminés.

## Périmètre vérifié

- Dix espaces : Tableau de bord, Gestion Blanchiments, Gestion Machines, Véhicule tombola, Historique, Statistiques, Équipe, Mon Registre, Le Conseil des Accès et Journal permanent.
- Routes de connexion, session et déconnexion ; profils et photos ; API des pages et mutations ; administration ; événements signés du connecteur.
- Règles métier, montants, progression, archives, pagination, imports, statistiques et journal.
- Chargements, erreurs réseau/serveur, délai d’expiration, double clic, annulation d’une navigation et réponses tardives.
- Ressources statiques, structure HTML, navigation accessible, petits écrans et animation de fumée.
- Sauvegarde/restauration, intégrité SQLite, déchiffrement des jetons et présence des photos référencées.

## Corrections effectuées

### Requêtes et vérification Discord

Les formulaires contenant du JSON invalide, des clés répétées, une mauvaise séquence UTF-8, une profondeur excessive ou des nombres non finis sont refusés avec une erreur 400. Les valeurs Unicode invalides dans les paramètres de sécurité ne provoquent plus d’erreur 500. Les événements signés concernant un membre exigent un identifiant de membre valide.

Les réponses Discord sont validées avant utilisation : identité, rôles, positions, identifiants et durée des jetons. Une réponse JSON de mauvais type provoque une erreur contrôlée, sans création de compte ou de session et sans exposition de secret.

Une course a été reproduite : une vérification Discord déjà en cours pouvait écraser une invalidation reçue du connecteur. Le traitement de l’événement partage maintenant le verrou des vérifications. Après l’accusé de réception de l’événement, l’ancienne réponse ne peut plus rétablir cet état dans le worker actuel. Tests réussis pour changement de rôle prioritaire, retrait Employé et départ du serveur.

### Corps de requêtes et journal permanent

La mémoire des corps HTTP fragmentés dépend maintenant de leur taille en octets, plutôt que du nombre de fragments. La limite de 2 Mo est conservée.

Une annulation pendant l’attente d’une place dans la file du journal ne perd plus le log déjà accepté. L’arrêt normal attend aussi ces soumissions. Les réponses attendent toujours leur validation durable ; les mutations et leurs valeurs avant/après restent atomiques. Les logs ne sont pas purgés.

### Montants, archives et imports

- Un montant numérique JSON `1000000.0` reste un million ; les fractions ne sont plus interprétées comme des séparateurs de milliers.
- Un prix Tombola numérique `0` reste zéro et ne devient plus un prix absent.
- Une pagination de plusieurs milliers de chiffres est refusée proprement.
- Un dossier annulé ne conserve plus de crédit dans le cas de réconciliation reproduit sans dossier ouvert restant.
- L’année explicite d’une archive telle que `2025-s42` est conservée.
- Les dates abrégées sont rattachées correctement aux semaines ISO qui chevauchent décembre et janvier.
- Les anciens numéros d’archives non ISO restent importables sans date inventée.
- `NaN` et les infinis sont refusés avant sauvegarde ou écriture de l’instantané.
- La conversion d’un instantané et les catalogues initiaux ne partagent plus d’objets modifiables avec leur source.

Les parts 15/80/5, l’attribution FIFO, les clôtures répétées sans écrasement, le lot unique et la récupération à l’échéance ont été revérifiés.

### Navigation et formulaires

- Les réponses tardives du profil, du Conseil, du catalogue et des archives ne réécrivent plus une page quittée.
- Les soumissions répétées du profil et les clics de pagination répétés du journal sont protégés.
- Une réponse 200 sans métadonnées de page valides provoque une erreur lisible, sans boucle de requêtes. Une vraie incohérence d’identité autorise au maximum une resynchronisation avant refus.
- Le brouillon du profil peut être conservé en RAM pendant une panne, reste masqué jusqu’à réautorisation et est supprimé au changement de compte ou à la déconnexion. Il n’est pas enregistré dans localStorage.
- Les titres, le fil de navigation et `aria-current` suivent aussi Mon Registre, Conseil et Journal.
- Les notifications vides affichent un état utile ; les menus respectent leur état ouvert/fermé et Escape.
- Les identifiants Tombola importés sont échappés dans les attributs HTML.
- Un favicon local évite la requête manquante répétée.
- La fumée démarre après l’ouverture du domaine sans clic et se met en pause sur l’accueil.

Les CSS, les couleurs, les dimensions et les effets de survol du design choisi n’ont pas été refaits.

## Tests exécutés

| Contrôle | Résultat |
|---|---|
| Suite complète Python sur bases temporaires | **237 réussis**, 0 échec |
| Compilation Python et scripts conservés | Réussie |
| Cohérence des dépendances installées (`pip check`) | Aucune dépendance incohérente |
| Ressources CSS/JS/images référencées et IDs HTML | Aucun fichier manquant dans le contrôle, aucun ID dupliqué |
| Pagination, recherche différée, focus, données à la demande | Réussis dans Firefox |
| Création/modification/restitution de dossier, tri récent, reset et consultation de l’archive | Réussis dans Firefox, base isolée |
| Sélection des rôles et enregistrement de la grille des accès | Réussis dans Firefox, base isolée |
| Envoi de photo puis affichage dans Équipe | Réussi dans Firefox, base isolée |
| Fumée, réponses tardives, brouillon profil, injection dans identifiant importé | Réussis dans Firefox, 0 erreur frontend non gérée dans ce parcours |
| Pannes au démarrage et sur pages, JSON invalide, réseau coupé, attente de 20 s, reprise | Réussis dans Firefox |
| Écriture échouée : saisies gardées et aucune répétition automatique | Réussi |
| Cycle machines : bouton bloqué avant fin, déblocage, récupération explicite avant nouveau lot | Réussi |
| Plafond visiteur/fournisseur, Retry-After, retour après attente | Réussis |
| Cache : un GET autorisé, 304, refus avant restitution, changement externe, filtres et expiration | Réussis |
| Journal : avant/après, échappement, détail à la demande, pagination, filtre vide, erreur différée | Réussis |
| Dix pages en largeur 390 px | Aucun débordement horizontal de la page |
| Restauration de la copie réelle : base, configuration privée, clé, photo et anciens logs | Réussie ; sources lues seulement |
| Dix pages du serveur actif après redémarrage | Réponses correctes, aucun chargement permanent reproduit |

Les tests Discord et Google Sheets utilisent des fournisseurs simulés. Aucun import depuis les vrais services ni message Discord n’a été envoyé pendant cette vérification. Les tests métier s’exécutent dans des bases temporaires.

## Données et performances après activation

Une sauvegarde privée `data/backup-before-full-review-1792818839377107317.sqlite3` a précédé le redémarrage. Les comptes, rôles, permissions, sessions et document métier ont été comparés par empreinte et restent inchangés. Les **599 anciens logs** contrôlés sont conservés à l’identique. Les anciennes clés d’opérations sont également conservées ; un nouveau signalement technique du navigateur s’est ajouté normalement. Le contrôle SQLite répond `ok` et les fichiers privés contrôlés ont les permissions `0600`.

Dernier parcours Firefox sur la preview active : document chargé en environ **1,45 s à l’ouverture**, **0,73 s au rechargement**, avec fumée réellement en lecture. Le premier audit mesurait environ 4 secondes avec la fumée en pause. Une seconde passe des pages a pris environ **0,14–0,79 s** par page. Ces valeurs sont des échantillons locaux, avec variabilité du disque et du rendu, pas des garanties pour tous les appareils.

Le navigateur automatisé fonctionne sans écran : son rendu vidéo n’est pas représentatif de toutes les cartes graphiques. La fluidité graphique de Brave/Chrome/Edge sur le PC utilisateur n’a pas été mesurée ici.

## Points restant à décider ou à développer

1. **Mise en ligne.** Discord reste temporairement désactivé pour la preview locale. La connexion réelle, HTTPS, le proxy, le service de démarrage et la supervision doivent être validés avant exposition publique. Aucune mise en production effectuée.
2. **Site et bot.** L’intégration métier est un import manuel en lecture. Les opérations du site ne sont pas encore transmises au bot ou à Google Sheets.
3. **Reset et anciennes semaines.** Le bot conserve son mécanisme automatique ; la preview n’a pas son propre worker hebdomadaire. Les anciens onglets bot `sNN` sont séquentiels : une correspondance calendrier fiable demande une année ou une date explicite. Le recalcul complet des classements des anciennes semaines après correction reste à développer.
4. **Corrections par employé.** L’accès Machines permet toujours de corriger un lot tiers. Une restriction « ses opérations seulement » n’a pas été activée pendant ce contrôle ; les droits de récupération d’un lot tiers restent autorisés comme demandé.
5. **Sauvegardes hors machine.** L’essai local de restauration complète est désormais réalisé et reproductible. Le choix d’une destination externe et la programmation des sauvegardes restent à faire.
6. **Plusieurs processus de serveur.** Le verrou de révocation ajouté protège le worker unique actuel. Une future configuration à plusieurs workers devra coordonner les invalidations entre processus.
7. **Contrôles complémentaires.** Brave/Chrome/Edge ne sont pas installés dans cet environnement. Pas de test d’intrusion externe, de charge prolongée ni de recherche exhaustive des vulnérabilités publiées des dépendances. `pip check` vérifie leur cohérence, pas l’absence de CVE.

## Relancer les principaux contrôles

Depuis `preview-discord/` :

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
.venv/bin/python tests/browser_frontend.py
.venv/bin/python tests/browser_workflows.py
.venv/bin/python scripts/verify_restore.py
```

Les parcours navigateur demandent Firefox avec Marionette. Ils utilisent un serveur local éphémère et une base séparée ; ils ne doivent pas être remplacés par des essais d’écriture sur la base active. Le script de restauration crée des copies temporaires privées et les supprime après vérification ; il ne remplace pas une sauvegarde hors machine.
