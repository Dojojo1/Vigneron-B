"""Preview or import available weekly archives; never creates Discord operations."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from backend.config import Settings
from backend.storage import Store
from backend.weekly_history import validate_archives,import_archives
from scripts.import_company_history import existing_database,read_state,backup_database


def main(argv=None,*,settings=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--database',type=Path)
    parser.add_argument('--backup-dir',type=Path)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args(argv);cfg=settings or Settings.load()
    if not args.reference.is_file() or args.reference.stat().st_size>5000000:raise ValueError('Fichier d’archives absent ou trop volumineux.')
    data=validate_archives(json.loads(args.reference.read_text(encoding='utf-8-sig')))
    database=existing_database(args.database or cfg.data_dir/'heritage-test.sqlite3');read_state(database)
    if not args.apply:
        result={'mode':'preview','dataModified':False,'weeks':len(data['worksheets']),'rows':sum(len(s['rows']) for s in data['worksheets'])}
    else:
        backup=backup_database(database,args.backup_dir or Path.home()/'.local/state/heritage/sauvegardes')
        store=Store(database)
        with store.connect(True) as db:result=import_archives(db,store,str(cfg.supreme_id),data)
        result={'mode':'applied','backup':str(backup),**result}
    print(json.dumps(result,ensure_ascii=False));return result

if __name__=='__main__':
    try:main()
    except (ValueError,OSError) as exc:
        print(str(exc),file=sys.stderr);raise SystemExit(1)
