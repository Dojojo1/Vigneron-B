"""One-time, non-destructive baseline for the two new sales and three exclusions."""
import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.coffre import SCHEMA, CONTROL_EVENT


SALE_IDS = ('1571966486782939269', '1571966567963435083')
EXCLUSIONS = (
    ('1571982221206884475', 'Argent obtenu avant le dépôt des 10 M$', None),
    ('1571981977362632746', 'Argent obtenu avant le dépôt des 10 M$', None),
    ('1571982737936482376', 'Retrait lié à une ancienne fiche', '1571228197054451833'),
)


def seed(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file() or path.suffix != '.sqlite3':
        raise ValueError('Base SQLite attendue.')
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        state = json.loads(db.execute('SELECT body FROM domain_store WHERE id=1').fetchone()['body'])
        sales = {row['id']: row for row in state['sales']}
        selected = [sales[identifier] for identifier in SALE_IDS]
        if any(row.get('botStatus') != 'confirmed' or row.get('amount') != 5000000
               or row['created'] / 1000 < CONTROL_EVENT for row in selected):
            raise ValueError('Les deux dossiers ne correspondent plus au point de départ attendu.')
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='coffre_checks'").fetchone()
        existing = db.execute('SELECT count(*) FROM coffre_checks').fetchone()[0] if exists else 0
        if existing:
            raise ValueError('Le contrôle a déjà un point de départ ; aucune donnée modifiée.')
        backup_dir = path.parent / 'backups'
        if not backup_dir.is_dir():
            raise ValueError('Dossier privé de sauvegarde absent.')
        backup = backup_dir / ('before-coffre-check-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.sqlite3')
        if backup.exists():
            raise ValueError('La sauvegarde existe déjà.')
        with sqlite3.connect(backup) as copy:
            db.backup(copy)
        db.executescript(SCHEMA)
        with db:
            db.executemany('INSERT INTO coffre_checks VALUES(?,?,?,?)',
                           [(row['id'], CONTROL_EVENT, 0, row['amount']) for row in selected])
            db.executemany('INSERT INTO coffre_log_exclusions VALUES(?,?,?)', EXCLUSIONS)
        return backup
    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    args = parser.parse_args()
    print('Point de départ enregistré ; sauvegarde privée :', seed(args.database))
