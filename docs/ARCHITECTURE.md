# Architecture du site

Ce dossier contient uniquement le site L’Héritage.

- `static/` : interface, styles, catalogue et essais enregistrés dans le navigateur.
- `index.html` : entrée GitHub Pages générée par `scripts/sync_pages.py`.
- `backend/` : fonctions du site en Python : comptes, droits, sessions et opérations.
- `scripts/` : lancement et outils de vérification du site.
- `tests/` : tests des opérations, des comptes et des interfaces.

GitHub Pages utilise les essais locaux du navigateur. Le backend Python reste
nécessaire pour les vrais comptes et données partagées. Son authentification
Discord est une fonction du site ; ce dossier ne démarre aucun bot Discord.

Le programme du bot reste séparé. Le transport optionnel `backend/bot_bridge.py`
reçoit des événements signés et conserve les opérations à transmettre au bot.
`connectors/website_client.py` est à charger dans le bot existant pour ces échanges.
La configuration est décrite dans `CONNEXION-BOT.md`. Aucun bot n’est démarré ici.
Le catalogue des véhicules et les règles de formulaire sont conservés dans le site.
