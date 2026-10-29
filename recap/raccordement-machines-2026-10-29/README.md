# Dossier à transmettre à l’assistant du site

Lire d’abord **RECAP-TECHNIQUE.md**, puis **CONTRAT-COMMUNICATION.md** et les corps JSON complets dans **exemples/**. Les trois audits détaillés sont dans **audits/**.

Statut : code Machines présent et liaison activée/vérifiée passivement ; recette métier réelle depuis le site et plusieurs correctifs de fiabilité restent à faire. Ce n’est pas une déclaration de raccordement entièrement terminé.

## Code sans données privées

- `sources/bot/` : moteur, connecteur, client et tests génériques exacts ; contexte des rappels extrait du bot.
- `sources/site/` : copies des fichiers génériques concernés. Une valeur de fixture de test est anonymisée, explicitement signalée dans `OMISSIONS.md`.
- `patches/site-exact.patch` : changements des 19 fichiers du site par rapport à la sauvegarde source antérieure ; le code d’exécution est exact, la fixture citée est anonymisée. Certains hunks n’ont pas de contexte pour exclure des noms/identifiants privés inchangés.
- `patches/bot-machines.astpatch.json` : sources exactes des fonctions/classes Machines et insertion du hook de démarrage. Le bot.py complet est volontairement absent : il contient aussi des constantes identifiantes qui ne doivent pas être transmises.
- `SOURCES-ORIGINALES.json` : empreintes des sources auditées.
- `INVENTAIRE.json` : chemins réels et nature des modifications, sans contenu privé.
- `MANIFEST.json` : empreintes des fichiers réellement livrés dans ce dossier.

Aucun `.env`, token, secret de production, clé Google, base, rappel réel ou sauvegarde n’est livré. Les secrets présents dans certains tests sont des constantes de test fictives, pas le secret partagé des programmes.

## Revue et application contrôlée

Les projets audités contiennent déjà ces modifications. Ne pas réappliquer les patchs dessus sans vérifier leur version. Pour une copie antérieure correspondante, rendre d’abord un candidat bot sans changer l’original :

```bash
python3 outils/appliquer_patch_bot.py /chemin/du/bot.py patches/bot-machines.astpatch.json --output /tmp/bot-candidat.py
```

La génération doit être revue par diff ; elle préserve les constantes privées non listées, ne lance pas le bot et ne remplace pas la cible. Les trois modules d’exécution associés sont à prendre dans `sources/bot/` : `machine_operations.py`, `bot_website_bridge.py`, `website_client.py`.

Depuis une copie **antérieure** du projet site :

```bash
git apply --check --unidiff-zero /chemin/du/dossier/patches/site-exact.patch
git apply --unidiff-zero /chemin/du/dossier/patches/site-exact.patch
```

Un échec de `--check` demande une revue ; ne pas forcer ni remplacer les fichiers du site par ceux du bot. Le patch a été vérifié dans un dossier temporaire contenant la sauvegarde préalable ; aucun patch n’a été appliqué à la production lors de ce récapitulatif.

L’outil `outils/redemarrer_site.py` est fourni pour une commande de redémarrage contrôlée, mais n’a pas été exécuté pour arrêter ou relancer le site. Ses usages et les commandes du service du bot sont dans le récapitulatif.

La courte procédure d’aller-retour réel sans doublon termine `RECAP-TECHNIQUE.md`. Elle reste à exécuter par un responsable autorisé.
