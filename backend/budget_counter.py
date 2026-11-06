"""Compteurs SQLite atomiques réutilisables par le serveur et son export Google."""
import hashlib
import math
import os
import sqlite3
import threading
import time
from collections import OrderedDict
from contextlib import closing
from pathlib import Path


class LimitReached(Exception):
    def __init__(self, retry_after):
        self.retry_after = max(1, math.ceil(retry_after))


class WindowCounters:
    def __init__(self, path, clock=time.time, reservation_size=8, reservation_cache_size=512):
        self.path, self.clock = Path(path), clock
        if reservation_size < 1 or reservation_cache_size < 1:
            raise ValueError('Les réservations et leur cache doivent être strictement positifs')
        self.reservation_size = reservation_size
        self.reservation_cache_size = reservation_cache_size
        self._reservations = OrderedDict()
        self._reservation_lock = threading.Lock()
        self._reservation_pid = os.getpid()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS counters(
                    category TEXT NOT NULL, subject TEXT NOT NULL, start INTEGER NOT NULL,
                    used INTEGER NOT NULL, expires INTEGER NOT NULL,
                    PRIMARY KEY(category,subject,start));
                CREATE INDEX IF NOT EXISTS counters_expiry ON counters(expires);
            ''')
        self.path.chmod(0o600)

    def consume(self, subject, rules):
        """Réserver toutes les fenêtres ou aucune ; compter avant l'appel réseau."""
        now = self.clock()
        subject = hashlib.sha256(subject.encode()).hexdigest()
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM counters WHERE expires<=?', (now,))
            windows = []
            blocked = []
            for category, maximum, seconds in rules:
                start = int(now // seconds) * seconds
                row = db.execute('SELECT used FROM counters WHERE category=? AND subject=? AND start=?',
                                 (category, subject, start)).fetchone()
                if row and row[0] >= maximum:
                    blocked.append(start + seconds - now)
                windows.append((category, subject, start, start + seconds))
            if blocked:
                raise LimitReached(max(blocked))
            for category, key, start, expires in windows:
                db.execute('''INSERT INTO counters VALUES(?,?,?,1,?)
                              ON CONFLICT(category,subject,start) DO UPDATE SET used=used+1''',
                           (category, key, start, expires))

    def consume_reserved(self, subject, rules):
        """Consommer un ticket visiteur précompté durablement, sans dépasser un plafond.

        Les quotas des fournisseurs utilisent toujours consume(), appel par appel.
        Ici, chaque petit bloc est débité en base AVANT d'être utilisable en mémoire.
        Un arrêt ou une éviction peut perdre ses tickets inutilisés, jamais les rendre
        disponibles une seconde fois. Les règles d'une requête restent indivisibles.
        """
        # Une copie héritée après fork ne doit jamais réutiliser les tickets du parent
        # ni son verrou, éventuellement verrouillé par un autre thread au moment du fork.
        if self._reservation_pid != os.getpid():
            self._reservations = OrderedDict()
            self._reservation_lock = threading.Lock()
            self._reservation_pid = os.getpid()
        subject = hashlib.sha256(subject.encode()).hexdigest()
        with self._reservation_lock:
            now = self.clock()
            for key, entry in list(self._reservations.items()):
                if entry['expires'] <= now:
                    del self._reservations[key]
            entries, missing = {}, []
            for category, maximum, seconds in rules:
                start = int(now // seconds) * seconds
                # Inclure les limites protège aussi un changement de configuration :
                # les anciens tickets ne peuvent servir à un nouveau plafond.
                key = (category, subject, start, maximum, seconds)
                if key in entries:
                    raise ValueError('Une règle ne peut apparaître deux fois')
                entry = self._reservations.get(key)
                entries[key] = entry
                if entry is None:
                    missing.append((key, start + seconds))
            if missing:
                allocations, blocked = {}, []
                with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
                    db.execute('BEGIN IMMEDIATE')
                    db.execute('DELETE FROM counters WHERE expires<=?', (now,))
                    for key, expires in missing:
                        category, subject_key, start, maximum, _ = key
                        row = db.execute(
                            'SELECT used FROM counters WHERE category=? AND subject=? AND start=?',
                            (category, subject_key, start)).fetchone()
                        available = maximum - (row[0] if row else 0)
                        if available <= 0:
                            blocked.append(expires - now)
                        allocations[key] = {'remaining': min(self.reservation_size, available), 'expires': expires}
                    if blocked:
                        raise LimitReached(max(blocked))
                    for key, entry in allocations.items():
                        category, subject_key, start, _, _ = key
                        db.execute('''INSERT INTO counters VALUES(?,?,?,?,?)
                                      ON CONFLICT(category,subject,start) DO UPDATE SET used=used+excluded.used''',
                                   (category, subject_key, start, entry['remaining'], entry['expires']))
                # Ne publier les tickets qu'après le COMMIT réussi de toutes les règles.
                entries.update(allocations)
            for key, entry in entries.items():
                entry['remaining'] -= 1
                if entry['remaining']:
                    self._reservations[key] = entry
                    self._reservations.move_to_end(key)
                else:
                    self._reservations.pop(key, None)
            while len(self._reservations) > self.reservation_cache_size:
                self._reservations.popitem(last=False)


