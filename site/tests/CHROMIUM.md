# Vérification Chrome / Chromium isolée

`browser_chromium.py` utilise ChromeDriver par son protocole HTTP WebDriver, sans Selenium. Il crée un serveur loopback, une base, des comptes fictifs et un profil navigateur dans un dossier temporaire. Il ne lit pas `.env` et interdit les appels aux fournisseurs Discord/Google. Les polices extérieures sont bloquées pour rendre ce contrôle indépendant du réseau.

Il faut deux binaires Linux compatibles : **Chrome for Testing** (ou **Chrome Headless Shell**) et **ChromeDriver de la même version**. La [documentation officielle](https://developer.chrome.com/docs/chromedriver/downloads/version-selection) renvoie aux [métadonnées de téléchargement officielles](https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json).

Pour la session de contrôle du 24 octobre 2026, les binaires officiels `156.0.8078.47` sont préparés uniquement sous `/tmp/heritage-chromium-audit/156.0.8078.47/`. Les deux archives font 137 682 360 octets au total ; rien n'est installé dans le système. Ces fichiers temporaires peuvent disparaître après un redémarrage. Les tailles, liens et empreintes SHA-256 des archives téléchargées sont consignés dans `/tmp/heritage-chromium-audit/binaries.json`.

Depuis `site/` :

```bash
.venv/bin/python tests/browser_chromium.py \
  --chrome-binary /tmp/heritage-chromium-audit/156.0.8078.47/chrome-headless-shell-linux64/chrome-headless-shell \
  --driver-binary /tmp/heritage-chromium-audit/156.0.8078.47/chromedriver-linux64/chromedriver \
  --workflows \
  --debug-transport pipe \
  --output-dir /tmp/heritage-chromium-audit/results-final
```

On peut aussi définir `CHROME_BINARY` et `CHROMEDRIVER_BINARY`. L'option `--no-sandbox` est disponible explicitement pour un conteneur qui refuse le sandbox Chrome ; elle n'est pas activée par défaut.

Le démarrage du pilote produit des journaux détaillés : `chromedriver.log`, `chromedriver-process.log` et `chrome.log`, conservés dans le dossier de sortie même après un échec. La création de session dispose de 75 secondes par défaut, réglables avec `--startup-timeout` ; les commandes ordinaires gardent leur délai de 35 secondes. `--debug-transport pipe` permet d'essayer le transport DevTools par pipe si la découverte du port échoue. Pour Headless Shell, le script n'ajoute pas le flag `--headless=new` destiné au mode unifié de Chrome complet. Il crée aussi un lanceur temporaire ouvrant `about:blank` : sans URL initiale, le Shell ne crée aucun onglet et ChromeDriver attend une page sans jamais la trouver. Un délai de session expiré ne constitue pas un test du site réussi.

Le contrôle vérifie le préchargement des dix espaces, le nombre de requêtes de données pendant la navigation, l'absence d'indicateur de chargement sur les pages mémorisées, les erreurs JavaScript, les propriétés CSS du fondu de la statue, les menus, la modale Tombola et les dix pages à 390 pixels. `--workflows` ajoute un véritable téléversement d'avatar **dans la base de test**, puis sa présence dans Équipe.

Exécution du 24 octobre : **réussie** avec `--no-sandbox --debug-transport pipe` dans le conteneur de test. Dix espaces préchargés, aucune requête de données ni indicateur pendant leur navigation, aucun débordement à 390 px, avatar normalisé et affiché dans Équipe, zéro erreur JavaScript dans ce parcours. Le masque alpha en dégradé de la statue est actif dans ce moteur Chromium.

Un succès émet un objet JSON avec les temps réellement mesurés et un code de sortie zéro. Un échec émet `ok: false` et un code de sortie non nul. Le dossier de sortie conserve des captures, `chromium-results.json` et le journal du pilote. Un contrôle Chrome ne remplace pas une exécution propre à Brave ou Edge.
