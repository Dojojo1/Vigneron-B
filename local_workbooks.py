"""Stockage SQLite des opérations, isolé dans le dossier de chaque Discord.

L'interface réduite permet aux mêmes actions Discord de conserver leurs références
de lignes et leurs archives, sans connexion ni identifiant Google.
"""
from contextlib import closing, contextmanager
import json
from pathlib import Path
import re
import sqlite3


def _cell(value):
    match = re.fullmatch(r'([A-Z]+)([1-9][0-9]*)', value.upper())
    if not match:
        raise ValueError('Référence de stockage invalide.')
    column = 0
    for letter in match[1]: column = column * 26 + ord(letter) - 64
    return int(match[2]), column


def _range(value):
    start, _, end = value.partition(':')
    r1, c1 = _cell(start); r2, c2 = _cell(end or start)
    if r2 < r1 or c2 < c1 or (r2-r1+1)*(c2-c1+1) > 1000000:
        raise ValueError('Plage de stockage invalide.')
    return r1, c1, r2, c2


class RoutingWorkbookClient:
    """Choisit le stockage par fonction et ne connecte Google qu'à la demande."""
    def __init__(self, local, google_ids, google_factory):
        self.local = local
        self.google_ids = set(google_ids)
        self.google_factory = google_factory
        self.google = None

    def open_by_key(self, identifier):
        if identifier in self.local.books:
            return self.local.open_by_key(identifier)
        if identifier not in self.google_ids:
            raise PermissionError('Ce registre ne fait pas partie de ce serveur.')
        if self.google is None:
            self.google = self.google_factory()
        return self.google.open_by_key(identifier)


class LocalWorkbookClient:
    def __init__(self, path, books):
        self.path, self.books = Path(path), dict(books)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect(True) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS books(id TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS sheets(id INTEGER PRIMARY KEY,book TEXT NOT NULL,title TEXT NOT NULL,UNIQUE(book,title));
                CREATE TABLE IF NOT EXISTS cells(sheet INTEGER NOT NULL,r INTEGER NOT NULL,c INTEGER NOT NULL,value TEXT NOT NULL,PRIMARY KEY(sheet,r,c),FOREIGN KEY(sheet) REFERENCES sheets(id));
            ''')
        self.path.chmod(0o600)

    @contextmanager
    def connect(self, write=False):
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.execute('PRAGMA foreign_keys=ON')
            if write: db.execute('BEGIN IMMEDIATE')
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def open_by_key(self, identifier):
        if identifier not in self.books:
            raise PermissionError('Ce stockage appartient à un autre serveur ou à une fonction désactivée.')
        with self.connect(True) as db:
            created = db.execute('INSERT OR IGNORE INTO books VALUES(?)', (identifier,)).rowcount
            if created:
                names = ('En cours', 'Modele') if self.books[identifier] == 'sales' else ('Blanchiments',)
                db.executemany('INSERT INTO sheets(book,title) VALUES(?,?)', [(identifier, name) for name in names])
        return LocalWorkbook(self, identifier)


class LocalWorkbook:
    def __init__(self, client, identifier): self.client, self.identifier = client, identifier

    def worksheet(self, title):
        with self.client.connect() as db:
            row = db.execute('SELECT id FROM sheets WHERE book=? AND title=?', (self.identifier, title)).fetchone()
        if row is None: raise LookupError('Archive ou registre local introuvable.')
        return LocalWorksheet(self, row[0])

    def worksheets(self):
        with self.client.connect() as db:
            return [LocalWorksheet(self, row[0]) for row in db.execute('SELECT id FROM sheets WHERE book=? ORDER BY id', (self.identifier,))]

    def values_batch_get(self, ranges):
        result = []
        for value in ranges:
            title, address = value.rsplit('!', 1)
            result.append({'values': self.worksheet(title.strip("'")).get(address)})
        return {'valueRanges': result}

    def archive(self, module, week_number=1):
        with self.client.connect(True) as db:
            titles = [row[0] for row in db.execute('SELECT title FROM sheets WHERE book=?', (self.identifier,))]
            pattern = r's([0-9]+)' if module == 'sales' else r'Semaine ([0-9]+)'
            numbers = [int(match[1]) for title in titles if (match := re.fullmatch(pattern, title))]
            number = max(numbers) + 1 if numbers else week_number if module == 'sales' else 1
            name = f's{number}' if module == 'sales' else f'Semaine {number}'
            title = 'En cours' if module == 'sales' else 'Blanchiments'
            row = db.execute('SELECT id FROM sheets WHERE book=? AND title=?', (self.identifier, title)).fetchone()
            if row is None: raise LookupError('Registre local introuvable.')
            if module == 'sales':
                db.execute('UPDATE sheets SET title=? WHERE id=?', (name, row[0]))
                model = db.execute('SELECT id FROM sheets WHERE book=? AND title=?', (self.identifier, 'Modele')).fetchone()[0]
                identifier = db.execute('INSERT INTO sheets(book,title) VALUES(?,?)', (self.identifier, title)).lastrowid
                db.execute('INSERT INTO cells SELECT ?,r,c,value FROM cells WHERE sheet=?', (identifier, model))
            else:
                identifier = db.execute('INSERT INTO sheets(book,title) VALUES(?,?)', (self.identifier, name)).lastrowid
                db.execute('INSERT INTO cells SELECT ?,r,c,value FROM cells WHERE sheet=?', (identifier, row[0]))
                db.execute('DELETE FROM cells WHERE sheet=? AND r>=8', (row[0],))
        return name


class LocalWorksheet:
    def __init__(self, book, identifier): self.book, self.id = book, identifier

    @property
    def title(self):
        with self.book.client.connect() as db:
            return db.execute('SELECT title FROM sheets WHERE id=? AND book=?', (self.id, self.book.identifier)).fetchone()[0]

    @property
    def row_count(self):
        with self.book.client.connect() as db:
            return max(200, db.execute('SELECT COALESCE(MAX(r),0) FROM cells WHERE sheet=?', (self.id,)).fetchone()[0])

    def get(self, address):
        r1,c1,r2,c2 = _range(address)
        with self.book.client.connect() as db:
            cells = {(r,c): json.loads(value) for r,c,value in db.execute('SELECT r,c,value FROM cells WHERE sheet=? AND r BETWEEN ? AND ? AND c BETWEEN ? AND ?', (self.id,r1,r2,c1,c2))}
        if not cells: return []
        last_row = max(r for r,c in cells)
        result = []
        for row in range(r1, last_row+1):
            values = [cells.get((row,column),'') for column in range(c1,c2+1)]
            while values and values[-1] == '': values.pop()
            result.append(values)
        return result

    def col_values(self, column):
        with self.book.client.connect() as db:
            values = {r:json.loads(value) for r,value in db.execute('SELECT r,value FROM cells WHERE sheet=? AND c=?', (self.id,column))}
        return [values.get(row,'') for row in range(1,max(values,default=0)+1)]

    def _write(self, db, changes):
        for change in changes:
            r1,c1,r2,c2 = _range(change['range'])
            for ri,values in enumerate(change['values']):
                for ci,value in enumerate(values):
                    if r1+ri>r2 or c1+ci>c2: raise ValueError('Écriture hors de la plage locale.')
                    if value == '':
                        db.execute('DELETE FROM cells WHERE sheet=? AND r=? AND c=?', (self.id,r1+ri,c1+ci))
                    else:
                        db.execute('INSERT INTO cells VALUES(?,?,?,?) ON CONFLICT(sheet,r,c) DO UPDATE SET value=excluded.value', (self.id,r1+ri,c1+ci,json.dumps(value,ensure_ascii=False)))

    def batch_update(self, changes):
        with self.book.client.connect(True) as db: self._write(db, changes)

    def update_acell(self, address, value): self.batch_update([{'range':address,'values':[[value]]}])

    def batch_clear(self, ranges):
        with self.book.client.connect(True) as db:
            for address in ranges:
                r1,c1,r2,c2 = _range(address)
                db.execute('DELETE FROM cells WHERE sheet=? AND r BETWEEN ? AND ? AND c BETWEEN ? AND ?', (self.id,r1,r2,c1,c2))

    def append_record(self, values, first_row):
        with self.book.client.connect(True) as db:
            occupied = {row[0] for row in db.execute('SELECT r FROM cells WHERE sheet=? AND c=2 AND r>=?', (self.id,first_row))}
            row = first_row
            while row in occupied: row += 1
            self._write(db, [{'range':f'{column}{row}','values':[[value]]} for column,value in values.items()])
        return row
