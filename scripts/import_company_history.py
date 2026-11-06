"""Preview or import a private owner-declared history reference; preview is readonly."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from backend.company_history import import_history, validate_history, project_history
from backend.config import Settings
from backend.storage import Store


def existing_database(path):
    path=Path(path).absolute()
    if path.is_symlink() or not path.is_file():
        raise ValueError('La base existante du Site Linux est nécessaire ; aucun nouveau fichier ne sera créé.')
    if hasattr(os,'geteuid') and path.stat().st_uid!=os.geteuid():
        raise ValueError('Exécute cet import avec le propriétaire de la base, sans sudo.')
    return path


def read_state(path):
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=15)) as db:
        db.execute('PRAGMA query_only=ON')
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'domain_store','users','audit','schema_version'}<=tables:
            raise ValueError('Ce fichier ne correspond pas à la base du Site Linux.')
        row=db.execute('SELECT body FROM domain_store WHERE id=1').fetchone()
        if row is None:raise ValueError('L’état existant du Site Linux est absent.')
        return json.loads(row[0])


def backup_database(path, directory):
    directory=Path(directory).absolute()
    for item in [directory,*directory.parents]:
        if item.is_symlink():raise ValueError('Le dossier de sauvegarde ne doit pas être un lien symbolique.')
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    if hasattr(os,'geteuid') and directory.stat().st_uid!=os.geteuid():
        raise ValueError('Le dossier de sauvegarde doit appartenir à l’utilisateur de la base.')
    directory.chmod(0o700)
    folder=Path(tempfile.mkdtemp(prefix='reprise-historique-',dir=directory))
    folder.chmod(0o700)
    destination=folder/'before.sqlite3';destination.touch(mode=0o600)
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=15)) as source:
        with closing(sqlite3.connect(destination)) as copy:
            source.backup(copy)
            if copy.execute('PRAGMA quick_check').fetchall()!=[('ok',)]:
                raise ValueError('La vérification de la sauvegarde a échoué.')
    destination.chmod(0o600)
    return destination


def run_import(reference,database,actor_id,*,apply=False,backup_dir=None,today=None):
    if not isinstance(actor_id,str) or not actor_id.isdigit():
        raise ValueError('L’identifiant du propriétaire doit être un identifiant Discord valide.')
    reference=Path(reference)
    if not reference.is_file() or reference.stat().st_size>20000:
        raise ValueError('Fichier de référence JSON absent ou trop volumineux.')
    data=validate_history(json.loads(reference.read_text(encoding='utf-8-sig')),today=today)
    database=existing_database(database)
    state=read_state(database)
    current=project_history(state)
    if not apply:
        return {'mode':'preview','dataModified':False,'reference':data,
                'currentReferenceId':current.get('id') if current else None,
                'existingReferenceValid':not state.get('companyHistory') or current is not None}
    backup=backup_database(database,backup_dir or Path.home()/'.local/state/heritage/sauvegardes')
    store=Store(database)
    with store.connect(True) as db:
        result=import_history(db,store,actor_id,data,today=today)
    return {'mode':'applied','backup':str(backup),**result}


def main(argv=None,*,settings=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,required=True,help='JSON privé contenant le cumul déclaré.')
    parser.add_argument('--database',type=Path,help='Base existante du Site Linux ; chemin habituel par défaut.')
    parser.add_argument('--backup-dir',type=Path,help='Dossier privé des sauvegardes avant import.')
    parser.add_argument('--apply',action='store_true',help='Appliquer la déclaration après sauvegarde ; absent = aperçu uniquement.')
    args=parser.parse_args(argv)
    cfg=settings or Settings.load()
    result=run_import(args.reference,args.database or cfg.data_dir/'heritage-test.sqlite3',
                      str(cfg.supreme_id),apply=args.apply,backup_dir=args.backup_dir)
    print(json.dumps(result,ensure_ascii=False))
    return result


if __name__=='__main__':
    try:main()
    except (ValueError,sqlite3.Error,OSError) as exc:
        print(str(exc),file=sys.stderr)
        raise SystemExit(1)
