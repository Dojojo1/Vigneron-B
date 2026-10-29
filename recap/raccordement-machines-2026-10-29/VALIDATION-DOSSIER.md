# Vérification du dossier transmissible — 29 octobre 2026

Ces contrôles ont été faits uniquement sur les fichiers du dossier et des répertoires/SQLite temporaires. Aucun fichier de production, service, secret ou état métier réel n’a été modifié.

- Le patch site a été appliqué après `git apply --check --unidiff-zero` dans une copie temporaire issue de la sauvegarde source préalable. Les 19 fichiers correspondent aux sources installées, sauf l’unique valeur de fixture explicitement anonymisée.
- Le patch AST du bot a généré un candidat distinct ; il est byte-identique au bot actuel. Le bot complet n’est pas exporté et ses constantes privées ne figurent pas dans le patch.
- Tous les fichiers Python livrés ont été compilés pour analyse syntaxique, sans exécution du bot ni de l’outil de restart.
- Tous les exemples JSON ont été parsés.
- Cinq exemples d’événements et six d’ACK ont traversé les méthodes réelles de vérification HMAC et de traitement du backend, avec un secret fictif uniquement en mémoire et de nouvelles bases SQLite temporaires. Tous ont été acceptés. Aucun appel HTTP réel, Discord ou Google n’a été effectué.
- Le paquet est construit à partir d’une liste de fichiers explicite, sans fichiers `.env`, bases, clés Google, sauvegardes ni logs réels. Les copies exportées ont été contrôlées pour exclure les constantes identifiantes du bot et les secrets privés des deux configurations, sans afficher leurs valeurs.

Le contrôle des patchs ne garantit pas leur application sur une version arbitraire d’un autre bot. Toujours faire `--check`, générer un candidat distinct et comparer avant toute installation. Les sources Linux auditées possèdent déjà ces modifications.
