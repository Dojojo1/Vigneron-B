# Regroupement du site — 25 octobre 2026

Une seule version utilisable : `site/`, issue de la dernière application FastAPI du dossier anciennement nommé `preview-discord/`. L’ancien site statique a été archivé sous `archives/ancien-site-20261025-185944.tar.gz`, puis retiré des dossiers utilisables. Les fichiers de l’archive ont été vérifiés par empreinte SHA-256, hors signal JSON réécrit périodiquement par le bot.

Point d’entrée : `./lancer-site.sh` à la racine du projet, adresse http://127.0.0.1:8081/. `site/run.sh` utilise le même lancement. Si le site tourne déjà, son adresse est affichée ; si un autre service occupe 8081, un message explicite invite à arrêter ce service, sans tuer de processus automatiquement.

La base a été sauvegardée avant déplacement : `site/data/backup-before-single-site-20261025-185944.sqlite3`. Les empreintes de la configuration privée, de la clé de chiffrement et des fichiers de données ont été contrôlées après déplacement. Les anciennes lignes des tables, sessions, rôles, permissions et logs sont conservées. Les chemins de l’environnement virtuel et des commandes de test ont été adaptés.

Le bot, ses services, ses JSON métier et son stockage local restent inchangés. Son chemin de publication du signal `site/sales-reset-state.json` est conservé. Aucun secret ne figure dans ce rapport ou dans l’interface. L’archive est privée et n’est pas servie par le backend.

Le regroupement ne change pas le mode local sans Discord actuellement activé, les données métier de test, les permissions des comptes ou la séparation actuelle entre site et bot. Il ne déploie rien en ligne.

## Vérifications après regroupement

- 314 tests Python du site réussis depuis le nouveau chemin ; 5 tests de compatibilité du signal de reset du bot réussis.
- Parcours Firefox : création d’un accès, doubles clics, connexion par code, catégories limitées, révocation de session et affichage mobile validés.
- Restauration temporaire complète : intégrité SQLite, 15 tables, configuration, photos, jetons chiffrés et ouverture des dix pages validées. Aucun appel Discord/Google pendant cette vérification.
- Sur le site actif : dix espaces préchargés, Conseil des Accès disponible, fichiers visuels disponibles. Anciennes lignes des tables métier, comptes, sessions et permissions inchangées ; les 1 211 anciennes entrées du journal conservées intégralement, les nouvelles traces étant ajoutées normalement.
- Relancer la commande lorsque le site est actif affiche son adresse sans lancer un second serveur. Environnement virtuel déplacé opérationnel, dépendances cohérentes et scripts shell/Python vérifiés.
- L’ancien dossier source temporaire a été supprimé après contrôle de l’archive. Il ne reste qu’un dossier de site utilisable, `site/`.
