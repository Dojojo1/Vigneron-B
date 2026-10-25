from contextlib import contextmanager
from pathlib import Path
import json
import os
import sqlite3
import time
from .auditing import clean, context, differences

SCHEMA = '''
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_version VALUES(1);
CREATE TABLE IF NOT EXISTS users(
 id TEXT PRIMARY KEY, username TEXT NOT NULL, discord_avatar TEXT NOT NULL DEFAULT '',
 display_name TEXT, avatar_file TEXT, created REAL NOT NULL, last_login REAL NOT NULL,
 member INTEGER NOT NULL DEFAULT 1, role_ids TEXT NOT NULL DEFAULT '[]', checked_at REAL NOT NULL DEFAULT 0,
 access_token TEXT NOT NULL, refresh_token TEXT NOT NULL, token_expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS roles(id TEXT PRIMARY KEY, name TEXT NOT NULL, position INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS role_permissions(role_id TEXT NOT NULL, page_id TEXT NOT NULL, allowed INTEGER NOT NULL CHECK(allowed IN (0,1)), PRIMARY KEY(role_id,page_id));
CREATE TABLE IF NOT EXISTS access_roles(role_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), csrf TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS oauth_states(hash TEXT PRIMARY KEY, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, actor TEXT, kind TEXT NOT NULL, detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS event_nonces(nonce TEXT PRIMARY KEY,expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS domain_store(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS operation_keys(user_id TEXT NOT NULL,key TEXT NOT NULL,fingerprint TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(user_id,key));
CREATE TABLE IF NOT EXISTS site_access_blocks(
 user_id TEXT PRIMARY KEY REFERENCES users(id),blocked_at REAL NOT NULL,blocked_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS access_accounts(
 user_id TEXT PRIMARY KEY REFERENCES users(id),login_name TEXT NOT NULL UNIQUE,
 code_hash TEXT NOT NULL,pages TEXT NOT NULL DEFAULT '[]',expires_at REAL,
 created_by TEXT NOT NULL,updated_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions(user_id);
CREATE INDEX IF NOT EXISTS sessions_expiry_idx ON sessions(expires);
CREATE INDEX IF NOT EXISTS oauth_expiry_idx ON oauth_states(expires);
CREATE INDEX IF NOT EXISTS nonces_expiry_idx ON event_nonces(expires);
CREATE INDEX IF NOT EXISTS users_members_created_idx ON users(member,created,id);
CREATE INDEX IF NOT EXISTS users_login_idx ON users(last_login DESC,id);
CREATE INDEX IF NOT EXISTS audit_actor_idx ON audit(actor,id DESC);
CREATE INDEX IF NOT EXISTS audit_kind_idx ON audit(kind,id DESC);
CREATE INDEX IF NOT EXISTS audit_at_idx ON audit(at,id DESC);
CREATE INDEX IF NOT EXISTS audit_page_idx ON audit(json_extract(detail,'$.page'),id DESC);
CREATE INDEX IF NOT EXISTS audit_result_idx ON audit(json_extract(detail,'$.result'),id DESC);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT,'Journal permanent : modification interdite'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'Journal permanent : suppression interdite'); END;
'''

class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.exists():
            with sqlite3.connect(self.path) as db:
                needs_backup=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='audit'").fetchone() and not db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='audit_no_delete'").fetchone()
                if needs_backup:
                    backup=self.path.with_name(f'backup-before-permanent-audit-{time.time_ns()}.sqlite3')
                    with sqlite3.connect(backup) as destination: db.backup(destination)
                    backup.chmod(0o600)
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone() and not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='access_accounts'").fetchone():
                    backup=self.path.with_name(f'backup-before-site-access-{time.time_ns()}.sqlite3')
                    with sqlite3.connect(backup) as destination:db.backup(destination)
                    backup.chmod(0o600)
        with self.connect() as db:
            db.executescript(SCHEMA)
        with self.connect(True) as db:
            if not db.execute("SELECT 1 FROM metadata WHERE key='role_selection_initialized'").fetchone():
                # Preserve permissions already configured before role selection existed.
                db.execute('INSERT OR IGNORE INTO access_roles SELECT DISTINCT role_id FROM role_permissions')
                db.execute("INSERT INTO metadata VALUES('role_selection_initialized','1')")
        self.path.chmod(0o600)

    @contextmanager
    def connect(self, write=False):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            if write: db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def audit(self, db, actor, kind, detail):
        detail=clean(detail)
        if 'before' in detail and 'after' in detail and 'changes' not in detail:
            detail['changes']=differences(detail['before'],detail['after'])
        detail.setdefault('result','failure' if kind.endswith('_failed') else 'success')
        if actor:
            row=db.execute('SELECT username,display_name FROM users WHERE id=?',(actor,)).fetchone()
            detail.setdefault('actorName',(row['display_name'] or row['username']) if row else str(actor))
        detail={**(context.get() or {}),**detail}
        db.execute('INSERT INTO audit(at,actor,kind,detail) VALUES(?,?,?,?)', (time.time(), actor, kind, json.dumps(detail, ensure_ascii=False)))

    def read_user(self, user_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
            return dict(row) if row else None

    def read_domain(self, fields=None, array_counts=()):
        """Ne décoder que les collections nécessaires à la page demandée."""
        if fields is None:
            with self.connect() as db:
                return json.loads(db.execute('SELECT body FROM domain_store WHERE id=1').fetchone()[0])
        columns=[];params=[]
        for field in fields:
            columns.extend(['json_extract(body,?)','json_type(body,?)']);params.extend(['$.'+field]*2)
        for field in array_counts:
            columns.append('json_array_length(body,?)');params.append('$.'+field)
        if not columns: return {}
        with self.connect() as db:
            row=db.execute('SELECT '+','.join(columns)+' FROM domain_store WHERE id=1',params).fetchone()
        result={}
        for index,field in enumerate(fields):
            value,kind=row[index*2],row[index*2+1]
            if kind is not None: result[field]=json.loads(value) if kind in ('array','object') else value
        for index,field in enumerate(array_counts): result['_count_'+field]=row[len(fields)*2+index] or 0
        return result
