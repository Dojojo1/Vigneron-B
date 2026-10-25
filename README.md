# L’Héritage — site unique

Le site actuel est dans `site/`. Ce dépôt contient le backend Python, le frontend,
les images, les animations et les tests de la dernière version. Le fichier `bot.py`
et ses modules sont conservés à la racine : le site lit ses fonctions pures de
progression sans démarrer le bot.

## Ce qui ne va pas sur GitHub

Les fichiers `.env`, les jetons, les clés Google, les environnements Python, les
bases SQLite, les comptes, les photos privées, les archives et les logs ne sont
pas dans cet export. Ils restent sur le PC Linux et ne sont pas effacés.
Le `.gitignore` les exclut aussi des futurs commits. La configuration publique
du code et les exemples de paramètres restent présents.

## Démarrage local sous Windows

Python 3.11 minimum est nécessaire. Dans PowerShell, depuis ce dossier :

```powershell
py -3 -m venv site\.venv
.\site\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item site\.env.example site\.env
.\site\.venv\Scripts\python.exe site\scripts\configure_oauth.py
.\site\.venv\Scripts\python.exe site\scripts\serve.py
```

La copie de `.env.example` concerne la première configuration seulement ; ne pas
remplacer un `.env` privé existant. La configuration OAuth2 reste à saisir en privé.
Le site neuf utilise ses données de démonstration tant que les données privées
Linux n’ont pas été transférées séparément. Le `.gitignore` ne constitue pas une
sauvegarde de ces données. Pour le mode local sans Discord, le paramètre privé
`HERITAGE_LOCAL_PREVIEW=1` conserve sa restriction à la machine locale.

Adresse locale : http://127.0.0.1:8081/.
L’environnement virtuel Linux n’est pas transféré : Windows recrée le sien.

## Démarrage local sous Linux

```bash
python3 -m venv site/.venv
site/.venv/bin/python -m pip install -r requirements.txt
cp site/.env.example site/.env
chmod 600 site/.env
site/.venv/bin/python site/scripts/configure_oauth.py
./lancer-site.sh
```

## GitHub et hébergement

GitHub conserve et versionne le code. GitHub Pages ne sert que des sites
statiques et ne fait pas tourner ce backend Python, indispensable aux comptes,
permissions et API. Il faudra un hébergeur capable d’exécuter Python, avec HTTPS
et stockage persistant, ou conserver le backend sur un PC correctement configuré.
Aucun hébergement public n’est activé par cet export. Le mode local sans Discord
doit être désactivé avant une mise en ligne validée.

La copie manuelle des données du bot nécessite toujours son environnement de
lecture et ses paramètres privés sur la machine d’exécution. Ce transfert de
code ne crée pas de synchronisation bidirectionnelle avec Discord.

Documentation : `site/README.md` et `site/ACCES-INDIVIDUELS.md`.
Référence GitHub Pages : https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages
