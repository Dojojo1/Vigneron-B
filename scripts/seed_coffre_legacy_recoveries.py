"""Freeze already recovered machines without dates before activating the coffre check."""
import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path


def seed(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file() or path.suffix != '.sqlite3':
        raise ValueError('Base SQLite attendue.')
    backup_dir = path.parent / 'backups'
    if not backup_dir.is_dir():
        raise ValueError('Dossier prive de sauvegarde absent.')
    backup = backup_dir / ('before-coffre-recoveries-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.sqlite3')
    if backup.exists():
        raise ValueError('La sauvegarde existe deja.')
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='coffre_legacy_recoveries'").fetchone()
        existing = db.execute('SELECT count(*) FROM coffre_legacy_recoveries').fetchone()[0] if table else 0
        if existing:
            raise ValueError('Le point de depart des recuperations existe deja.')
        state = json.loads(db.execute('SELECT body FROM domain_store WHERE id=1').fetchone()['body'])
        ids = [machine['id'] for machine in state.get('machines', [])
               if machine.get('botStatus') == 'confirmed' and machine.get('recovered') is True
               and not machine.get('cancelled') and type(machine.get('recoveredAt')) is not int]
        if len(ids) != len(set(ids)):
            raise ValueError('Identifiants de machines en double.')
        with sqlite3.connect(backup) as copy:
            db.backup(copy)
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS coffre_legacy_recoveries(machine_id TEXT PRIMARY KEY)')
            db.executemany('INSERT INTO coffre_legacy_recoveries VALUES(?)', [(value,) for value in ids])
    return backup, len(ids)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    args = parser.parse_args()
    print(seed(args.database))
