# Architecture du site

Ce dossier contient uniquement le site L’Héritage.

- `static/` : interface, styles, catalogue et essais enregistrés dans le navigateur.
- `index.html` : entrée GitHub Pages générée par `scripts/sync_pages.py`.
- `backend/` : fonctions du site en Python : comptes, droits, sessions et opérations.
- `scripts/` : lancement et outils de vérification du site.
- `tests/` : tests des opérations, des comptes et des interfaces.

GitHub Pages sert l'accueil et ouvre la connexion sur le backend configuré.
Les essais locaux du navigateur exigent un mode aperçu explicite. Le backend
Python reste nécessaire pour les vrais comptes et données partagées. Son authentification
Discord est une fonction du site ; ce dossier ne démarre aucun bot Discord.

Le programme du bot reste séparé. Le transport optionnel `backend/bot_bridge.py`
reçoit des snapshots Machines signés et conserve les demandes à transmettre au bot.
`connectors/website_client.py` est à charger dans le bot existant pour ces échanges.
La configuration est décrite dans `CONNEXION-BOT.md`. Aucun bot n’est démarré ici.
Le catalogue des véhicules et les règles de formulaire sont conservés dans le site.

En mode connecté, une demande Machines est mise en attente sans démarrer de
compteur. Le bot confirme l'état réel via `machine_sync` et un ACK contenant
le résultat. Les autres opérations restent gérées par le site et ne sont pas
présentées comme raccordées à Discord. Le contrat est décrit dans `CONNEXION-BOT.md`.
