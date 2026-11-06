"""Create a private, consistent backup before deploying either project."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sqlite3


EXCLUDE = {'.git', '.venv', '.venv-check', 'venv', '__pycache__', 'node_modules',
           'recap', 'exports', 'backups', 'CODEX_SAUVEGARDES', 'maintenance'}


def backup(site, bot, destination):
    roots = {'site': site.resolve(), 'bot': bot.resolve()}
    destination = destination.resolve()
    if any(not root.is_dir() for root in roots.values()):
        raise ValueError('Les dossiers du Site Linux et du Bot doivent exister.')
    if any(destination.is_relative_to(root) for root in roots.values()):
        raise ValueError('La sauvegarde doit être placée hors des deux projets.')
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    manifest = []
    for name, root in roots.items():
        for source in sorted(root.rglob('*')):
            relative = source.relative_to(root)
            if any(part in EXCLUDE for part in relative.parts) or not source.is_file():
                continue
            if not source.resolve().is_relative_to(root):
                raise ValueError('Un lien de données sort du dossier autorisé.')
            if source.suffix not in ('.sqlite3', '.sqlite', '.db', '.json', '.key', '.pem') and not source.name.startswith('.env'):
                continue
            target = destination/name/relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if source.suffix in ('.sqlite3', '.sqlite', '.db'):
                # SQLite backup includes committed WAL data without copying a live file.
                with sqlite3.connect(source.as_uri()+'?mode=ro', uri=True) as original:
                    target.touch(mode=0o600)
                    with sqlite3.connect(target) as saved:
                        original.backup(saved)
                        if saved.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                            raise ValueError('Une sauvegarde SQLite est incohérente.')
            else:
                with target.open('xb') as output:
                    target.chmod(0o600)
                    with source.open('rb') as original:
                        shutil.copyfileobj(original, output)
            target.chmod(0o600)
            manifest.append({'project': name, 'file': relative.as_posix(), 'bytes': target.stat().st_size})
    (destination/'MANIFEST.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    (destination/'MANIFEST.json').chmod(0o600)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, required=True)
    parser.add_argument('--bot', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    records = backup(args.site, args.bot, args.destination)
    print('Sauvegarde privée vérifiée :', args.destination)
    print('Fichiers conservés :', len(records))


if __name__ == '__main__':
    main()
