# L’Héritage

Site de gestion du domaine RP : interface web, serveur Python et bot Discord.

## Organisation

| Emplacement | Contenu |
| --- | --- |
| `index.html` | Accueil publié sur GitHub Pages |
| `static/` | Interface, styles, scripts, images et animations |
| `backend/` | Serveur FastAPI, comptes, permissions et données métier |
| `scripts/` | Lancement, configuration, export et vérifications |
| `integration/` | Extension de connexion au bot Discord |
| `tests/` | Tests Python et parcours navigateur |
| `docs/` | Documentation technique et fonctionnelle |
| `data/` | Données locales privées, exclues de GitHub |
| `bot.py` et modules à la racine | Bot Discord et règles partagées avec le serveur |

## GitHub Pages

Publier la branche depuis sa racine (`/`). Conserver `index.html` et le dossier
`static/` ensemble : l’accueil charge ses ressources depuis `./static/`.

GitHub Pages propose une démonstration accessible avec « Explorer le domaine ».
La navigation et les formulaires sont consultables avec des données fictives ;
les enregistrements ne sont pas encore activés dans cette démonstration.
Aucun appel au bot Discord ni aux API privées n’est effectué. Les vrais comptes,
la connexion Discord et les opérations privées nécessitent le serveur Python.

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
- [Préparation Supabase](docs/SUPABASE-PREPARATION.md)

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
