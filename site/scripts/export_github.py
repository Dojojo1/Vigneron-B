"""Exporter le code du site unique, sans configuration privée ni données utilisateur."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[2]
SITE=ROOT/'site'
GITIGNORE='''# Configuration privée et données : ne jamais publier
.env
.env.*
!.env.example
!**/.env.example
**/.venv/
**/venv/
**/__pycache__/
**/.pytest_cache/
**/node_modules/
**/data/**
!**/data/.gitkeep
**/archives/
**/exports/
**/backups/
**/avatars/
*.sqlite3*
*.sqlite*
*.db
*.db-*
*.key
*.pem
*credentials*.json
site/sales-reset-state.json
'''
README='''# L’Héritage — site unique

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
py -3 -m venv site\\.venv
.\\site\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt
Copy-Item site\\.env.example site\\.env
.\\site\\.venv\\Scripts\\python.exe site\\scripts\\configure_oauth.py
.\\site\\.venv\\Scripts\\python.exe site\\scripts\\serve.py
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
'''


def sources():
    paths=[]
    for name in ('backend','static','scripts','integration','tests'):
        for path in (SITE/name).rglob('*'):
            relative=path.relative_to(SITE/name)
            if path.is_symlink():raise ValueError('Lien symbolique inattendu dans le code à exporter.')
            if not path.is_file() or any(part.startswith('.') or part in ('__pycache__','node_modules','data') for part in relative.parts):continue
            if path.suffix in ('.pyc','.pyo','.sqlite3','.sqlite','.db','.key','.pem') or 'credentials' in path.name.lower():raise ValueError('Fichier privé inattendu dans les sources.')
            paths.append(path)
    paths.extend(path for path in SITE.glob('*.md') if path.is_file())
    paths.extend(SITE/name for name in ('.env.example','requirements.txt','requirements.lock','run.sh'))
    # Dépendance existante du calcul métier ; aucun import/démarrage du bot.
    paths.extend(ROOT/name for name in ('bot.py','bot_guilds.py','guild_setup.py','guild_sheets.py','local_workbooks.py','lancer-site.sh'))
    return sorted(set(paths))


def export(output):
    from dotenv import dotenv_values
    private_values=[]
    for path in (ROOT/'.env',SITE/'.env'):
        if path.is_file():
            for key,value in dotenv_values(path).items():
                if value and len(value)>=12 and any(word in key.upper() for word in ('TOKEN','SECRET','PASSWORD','PRIVATE_KEY')):
                    private_values.append(value.encode())
    contents={str(path.relative_to(ROOT)).replace('\\','/'):path.read_bytes() for path in sources()}
    bot_requirements=ROOT/'requirements-bot.txt'
    if not bot_requirements.is_file():bot_requirements=ROOT/'requirements.txt'
    contents.update({'.gitignore':GITIGNORE.encode(),'README.md':README.encode(),
                     'requirements.txt':b'-r site/requirements.lock\n-r requirements-bot.txt\n',
                     'requirements-bot.txt':bot_requirements.read_bytes()+b'\n',
                     'site/data/.gitkeep':b''})
    for name,body in contents.items():
        if any(value in body for value in private_values):raise ValueError('Un secret privé apparaît dans un fichier source : export refusé.')
        if len(body)>=100*1024*1024:raise ValueError('Fichier trop volumineux pour le dépôt GitHub.')
    manifest={'files':{name:hashlib.sha256(body).hexdigest() for name,body in sorted(contents.items())},
              'source':'site','privateDataIncluded':False,'pythonEnvironmentIncluded':False}
    contents['EXPORT-MANIFEST.json']=json.dumps(manifest,indent=2).encode()
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix='.github-export-',suffix='.zip',dir=output.parent,delete=False) as file:temporary=Path(file.name)
    try:
        with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            for name,body in sorted(contents.items()):
                entry=zipfile.ZipInfo(name)
                entry.create_system=3
                entry.external_attr=((0o100755 if name.endswith('.sh') else 0o100644)<<16)
                archive.writestr(entry,body,compress_type=zipfile.ZIP_DEFLATED,compresslevel=6)
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:raise ValueError('Archive invalide.')
        temporary.chmod(0o600);temporary.replace(output)
    finally:temporary.unlink(missing_ok=True)
    return {'archive':str(output),'files':len(contents),'bytes':output.stat().st_size,
            'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'privateDataIncluded':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'exports/Vigneron-B-github.zip')
    args=parser.parse_args()
    print(json.dumps(export(args.output),ensure_ascii=False))
