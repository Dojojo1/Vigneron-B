# L’Héritage

Pour connecter le site au bot existant, suivre [la configuration du raccordement](docs/CONNEXION-BOT.md).
Les IDs et secrets sont renseignés uniquement dans le `.env` privé ; l’entrée
GitHub Pages ne reçoit que l’adresse publique du backend.

Site de gestion du domaine RP : interface web et backend Python du site.

## Organisation

| Emplacement | Contenu |
| --- | --- |
| `index.html` | Accueil publié sur GitHub Pages |
| `static/` | Interface, styles, scripts, images et animations |
| `backend/` | Serveur FastAPI, comptes, permissions et données métier |
| `scripts/` | Lancement, configuration, export et vérifications |
| `tests/` | Tests Python et parcours navigateur |
| `docs/` | Documentation technique et fonctionnelle |
| `data/` | Données locales privées, exclues de GitHub |

## GitHub Pages

Publier la branche depuis sa racine (`/`). Conserver `index.html` et le dossier
`static/` ensemble : l’accueil charge ses ressources depuis `./static/`.

GitHub Pages affiche l’accueil avec « Se connecter avec Discord ». Le clic ouvre
la connexion OAuth2 sur le backend configuré dans `static/site-config.json`.
Les pages privées restent cachées avant authentification ; aucune session locale
n’est créée automatiquement en cas de configuration absente ou de panne réseau.
Les secrets restent exclusivement dans le `.env` privé du backend Python.

Les essais locaux restent disponibles uniquement avec le mode explicite
`python scripts/configure_connection.py --preview`. Ils ne donnent aucun accès
aux vrais comptes ou données Discord.

Ce dossier contient uniquement le site : le programme du bot et ses anciens connecteurs ont été retirés.

Les panneaux « Accès extérieurs » et « Droits et grades Discord » utilisent
le backend Python pour les vrais comptes et rôles. Le mode aperçu explicite
permet de préparer des réglages avec des grades d'exemple et des codes `APERCU-`
qui restent dans le navigateur. Ces codes ne donnent aucun accès réel.

Le raccordement Machines utilise une file de demandes et des confirmations
signées du bot existant. Il faut installer des versions compatibles dans les
deux projets et terminer les correctifs du bot avant la recette réelle.
Les détails sont dans [CONNEXION-BOT.md](docs/CONNEXION-BOT.md) et
[la passation des correctifs](docs/PASSATION-CORRECTIFS-BOT.md).

## Démarrage sous Windows

Installer Python 3.11 ou plus récent, puis dans PowerShell depuis ce dossier :

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe scripts\configure_oauth.py
.\.venv\Scripts\python.exe scripts\serve.py
```

Créer `.env` uniquement à la première installation ; conserver la configuration
privée existante. Adresse locale : http://127.0.0.1:8081/.

## Démarrage sous Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
.venv/bin/python scripts/configure_oauth.py
bash lancer-site.sh
```

Le mode `HERITAGE_LOCAL_PREVIEW=1` est réservé à une utilisation locale.
Les secrets, bases SQLite, photos privées et environnements Python restent
exclus du dépôt par `.gitignore`.

## Documentation

- [Accès individuels](docs/ACCES-INDIVIDUELS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Décisions fonctionnelles](docs/DECISIONS-FONCTIONNELLES.md)
- [Sécurité et fiabilité](docs/SECURITE-ET-FIABILITE.md)

Les documents techniques conservent le contexte des décisions et intégrations.
Les commandes de lancement à utiliser sont celles de ce README.

## Vérifier les modifications

Après une modification de `static/index.html`, régénérer l’accueil GitHub Pages :

```powershell
.\.venv\Scripts\python.exe scripts\sync_pages.py
```

Le test public utilise Node.js et Chrome, sans compte ni serveur Python :

```powershell
node tests/browser_pages.mjs
```

Il vérifie l’accueil sous `/Vigneron-B/`, quatre largeurs d’écran, l’absence
d’appels aux API privées, et la récupération après des fichiers manquants.
Les tests du serveur se lancent avec `python -m pytest tests` dans son environnement.
