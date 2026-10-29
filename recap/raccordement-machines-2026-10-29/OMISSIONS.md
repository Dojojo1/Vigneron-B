# Copie sans données privées

Aucun .env, aucune base, sauvegarde privée ou clé Google ne figure dans ce dossier.
EXCEPTION EXPLICITE : dans tests/test_machine_bridge.py, une valeur de launcher de test est anonymisée en Employé Exemple. Le code métier est exact ; cette fixture exportée diffère donc de l’original dont le hash figure dans SOURCES-ORIGINALES.json.
Le bot.py complet est remplacé par un patch AST exact de ses fonctions Machines, sans ses constantes privées.
Les fichiers suivants ne sont pas recopiés en entier car ils contiennent des données de configuration ou des fixtures identifiantes inchangées. Leurs changements exacts sont disponibles dans le patch du site, parfois sans contexte (git apply --unidiff-zero).

- `site/backend/domain.py`
- `site/static/app.js`
- `site/tests/test_business.py`
- `site/tests/test_business_preload_integrity.py`
- `site/tests/test_loading_and_requests.py`
- `site/tests/test_machine_lifecycle.py`
