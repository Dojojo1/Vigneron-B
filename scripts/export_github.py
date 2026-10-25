"""Exporter le code du site unique, sans configuration privée ni données utilisateur."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
SITE=ROOT
def sources():
    paths=[]
    for name in ('backend','static','scripts','integration','tests','docs'):
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
    for path in (ROOT/'.env',):
        if path.is_file():
            for key,value in dotenv_values(path).items():
                if value and len(value)>=12 and any(word in key.upper() for word in ('TOKEN','SECRET','PASSWORD','PRIVATE_KEY')):
                    private_values.append(value.encode())
    contents={str(path.relative_to(ROOT)).replace('\\','/'):path.read_bytes() for path in sources()}
    bot_requirements=ROOT/'requirements-bot.txt'
    if not bot_requirements.is_file():bot_requirements=ROOT/'requirements.txt'
    # L'entrée publiée est générée depuis l'unique interface, avec les mêmes
    # ressources. Les fonctions privées ne sont jamais simulées dans Pages.
    entry=(SITE/'static/index.html').read_text(encoding='utf-8').replace('<meta charset="utf-8">','<meta charset="utf-8">\n<base href="./static/">\n<meta name="heritage-hosting" content="github-pages">',1)
    contents.update({'.gitignore':(ROOT/'.gitignore').read_bytes(),'README.md':(ROOT/'README.md').read_bytes(),'index.html':entry.encode(),
                     'requirements.txt':b'-r requirements.lock\n-r requirements-bot.txt\n',
                     'requirements-bot.txt':bot_requirements.read_bytes()+b'\n',
                     'data/.gitkeep':b''})
    for name,body in contents.items():
        if any(value in body for value in private_values):raise ValueError('Un secret privé apparaît dans un fichier source : export refusé.')
        if len(body)>=100*1024*1024:raise ValueError('Fichier trop volumineux pour le dépôt GitHub.')
    manifest={'files':{name:hashlib.sha256(body).hexdigest() for name,body in sorted(contents.items())},
              'source':'.','privateDataIncluded':False,'pythonEnvironmentIncluded':False}
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
