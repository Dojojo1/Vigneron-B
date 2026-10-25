"""Configuration durable par serveur, partagée par le bot et sa page Setup.

Ce module ne contacte ni Discord ni Google et n'importe jamais bot.py.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent


class SetupValidationError(ValueError):
    pass


class SetupConflictError(ValueError):
    pass


def snowflake(value, field="Identifiant", optional=False):
    if optional and value in (None, ""):
        return None
    raw = str(value or "").strip()
    if not re.fullmatch(r"[0-9]{1,24}", raw) or int(raw) <= 0:
        raise SetupValidationError(f"{field} doit contenir un identifiant Discord valide.")
    return raw


def sheet_id(value):
    raw = str(value or "").strip()
    if raw.startswith("https://"):
        parsed = urlparse(raw)
        match = re.match(r"/spreadsheets/d/([A-Za-z0-9_-]+)(?:/|$)", parsed.path)
        if parsed.hostname != "docs.google.com" or parsed.username or not match:
            raise SetupValidationError("Utilise le lien Google Sheets du classeur.")
        raw = match.group(1)
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,128}", raw):
        raise SetupValidationError("Le lien ou l’identifiant Google Sheets est invalide.")
    return raw


def _ids(value, field, required=False):
    if value is None or value == "":
        value = []
    if not isinstance(value, list) or len(value) > 25:
        raise SetupValidationError(f"{field} : choisis au maximum 25 éléments.")
    result = list(dict.fromkeys(snowflake(item, field) for item in value))
    if required and not result:
        raise SetupValidationError(f"{field} est obligatoire pour cette fonction.")
    return result


def _text(value, field, maximum=100):
    if not isinstance(value, str) or len(value.strip()) > maximum or any(ord(c) < 32 for c in value):
        raise SetupValidationError(f"{field} est invalide (maximum {maximum} caractères).")
    return value.strip()


def _blank(value):
    if isinstance(value, dict):
        return all(_blank(item) for key, item in value.items() if key not in {"worksheet", "storage_mode"})
    if isinstance(value, list):
        return not value
    return value is None or value == "" or value is False


def storage_mode(config, module=None):
    mode = config.get("storage_mode", "google_sheets")
    if module is not None:
        mode = (config.get("modules", {}).get(module) or {}).get("storage_mode", mode)
    if mode not in ("google_sheets", "local"):
        raise SetupValidationError("Choisis Google Sheets ou le stockage sur le serveur.")
    return mode


def normalize_setup(guild_id, config):
    guild = snowflake(guild_id, "Serveur")
    if not isinstance(config, dict):
        raise SetupValidationError("La configuration doit être un formulaire JSON.")
    if config.get("guild_id") is not None and str(config["guild_id"]) != guild:
        raise SetupValidationError("La configuration appartient à un autre serveur.")
    employees = config.get("employees", [])
    groups = config.get("groups", [])
    if not isinstance(employees, list) or len(employees) > 25:
        raise SetupValidationError("Ajoute au maximum 25 personnes.")
    if not isinstance(groups, list) or len(groups) > 25:
        raise SetupValidationError("Ajoute au maximum 25 groupes.")
    people, seen_names, seen_ids = [], set(), set()
    for employee in employees:
        if not isinstance(employee, dict):
            raise SetupValidationError("Chaque personne nécessite un nom et un ID joueur.")
        name = _text(employee.get("name", ""), "Nom de la personne", 70)
        ident = str(employee.get("id", "")).strip()
        if not name or name.startswith("=") or not re.fullmatch(r"[0-9]{1,20}", ident):
            raise SetupValidationError("Chaque personne nécessite un nom et un ID joueur numérique.")
        if name.casefold() in seen_names or ident in seen_ids:
            raise SetupValidationError("Une personne ou un ID joueur apparaît plusieurs fois.")
        seen_names.add(name.casefold()); seen_ids.add(ident)
        people.append({"name": name, "id": ident})
    normalized_groups = []
    for value in groups:
        name = _text(value, "Nom du groupe")
        if not name or name.startswith("=") or name.casefold() in {item.casefold() for item in normalized_groups}:
            raise SetupValidationError("Les noms de groupes doivent être renseignés et uniques.")
        normalized_groups.append(name)
    modules = config.get("modules", {})
    if not isinstance(modules, dict) or set(modules) - {"sales", "machines", "tombola"}:
        raise SetupValidationError("La liste des fonctions est invalide.")
    mode = storage_mode(config)
    result = {"guild_id": guild, "storage_mode": mode, "company_name": _text(config.get("company_name", ""), "Nom de l’entreprise"),
              "employees": people, "groups": normalized_groups, "modules": {}}
    for module in ("sales", "machines", "tombola"):
        block = modules.get(module)
        if _blank(block):
            result["modules"][module] = None
            continue
        if not isinstance(block, dict):
            raise SetupValidationError(f"Le bloc {module} est invalide.")
        normalized = {"panel_channel_id": snowflake(block.get("panel_channel_id"), f"Salon du panneau {module}")}
        if module == "sales":
            normalized.update(channel_ids=_ids(block.get("channel_ids"), "Salons Sales"),
                add_role_ids=_ids(block.get("add_role_ids"), "Rôles autorisés à ajouter du sale", True),
                status_role_ids=_ids(block.get("status_role_ids"), "Rôles responsables du sale", True))
            normalized["channel_ids"] = list(dict.fromkeys([normalized["panel_channel_id"], *normalized["channel_ids"]]))
            if not people or not normalized_groups:
                raise SetupValidationError("La gestion du sale nécessite au moins une personne et un groupe.")
        else:
            normalized["role_ids"] = _ids(block.get("role_ids"), f"Rôles autorisés {module}", True)
        if module in ("sales", "machines"):
            module_mode = storage_mode(config, module)
            normalized["storage_mode"] = module_mode
            default = "En cours" if module == "sales" else "Blanchiments"
            if module_mode == "google_sheets":
                normalized["sheet_id"] = sheet_id(block.get("sheet_id"))
                normalized["worksheet"] = _text(block.get("worksheet") or default, "Nom de l’onglet")
            else:
                if block.get("sheet_id"):
                    raise SetupValidationError("Le stockage serveur ne nécessite pas de lien Google Sheets.")
                normalized["worksheet"] = default
        if module == "machines":
            normalized.update(reminder_channel_id=snowflake(block.get("reminder_channel_id"), "Salon des rappels"),
                reminder_role_id=snowflake(block.get("reminder_role_id"), "Rôle à notifier"))
            for key in ("stats_channel_id", "logs_channel_id"):
                normalized[key] = snowflake(block.get(key), key, True)
        if module == "tombola":
            normalized["log_channel_id"] = snowflake(block.get("log_channel_id"), "Salon de suivi Tombola", True)
        result["modules"][module] = normalized
    return result


def setup_sheet_ids(config):
    return {block["sheet_id"] for block in config.get("modules", {}).values()
            if isinstance(block, dict) and block.get("sheet_id")}


class GuildSetupStore:
    def __init__(self, path=None):
        self.path = Path(path or os.getenv("GUILD_SETUP_DB", ROOT / "guild_setup.sqlite3"))
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS guild_setups(guild_id TEXT PRIMARY KEY,config TEXT NOT NULL,revision INTEGER NOT NULL,updated_at TEXT NOT NULL,actor_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS setup_sheet_bindings(sheet_id TEXT PRIMARY KEY,guild_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS setup_module_sheets(guild_id TEXT NOT NULL,module TEXT NOT NULL,sheet_id TEXT NOT NULL,PRIMARY KEY(guild_id,module));
            CREATE TABLE IF NOT EXISTS setup_module_storage(guild_id TEXT NOT NULL,module TEXT NOT NULL,mode TEXT NOT NULL,PRIMARY KEY(guild_id,module));
            CREATE TABLE IF NOT EXISTS setup_challenges(guild_id TEXT NOT NULL,actor_id TEXT NOT NULL,token TEXT NOT NULL,expires REAL NOT NULL,PRIMARY KEY(guild_id,actor_id));
            CREATE TABLE IF NOT EXISTS setup_proofs(guild_id TEXT NOT NULL,actor_id TEXT NOT NULL,sheet_id TEXT NOT NULL,expires REAL NOT NULL,PRIMARY KEY(guild_id,actor_id,sheet_id));
            CREATE TABLE IF NOT EXISTS setup_sessions(hash TEXT PRIMARY KEY,body TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS setup_oauth_states(hash TEXT PRIMARY KEY,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS setup_actions(id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id TEXT NOT NULL,kind TEXT NOT NULL,actor_id TEXT NOT NULL,created REAL NOT NULL,completed REAL,error TEXT);
            CREATE TABLE IF NOT EXISTS setup_audit(id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id TEXT NOT NULL,actor_id TEXT NOT NULL,at TEXT NOT NULL,kind TEXT NOT NULL,detail TEXT NOT NULL);
            """)
            # Migration des configurations créées avant la protection par fonction.
            for row in db.execute("SELECT guild_id,config FROM guild_setups").fetchall():
                self._bind_module_sheets(db, row["guild_id"], json.loads(row["config"]))
        self.path.chmod(0o600)

    @contextmanager
    def connect(self, write=False):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            if write: db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback(); raise
        finally:
            db.close()

    def get(self, guild_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM guild_setups WHERE guild_id=?", (str(guild_id),)).fetchone()
        if not row: return None
        result = json.loads(row["config"])
        result.update(revision=row["revision"], updated_at=row["updated_at"])
        return result

    def list(self):
        with self.connect() as db:
            ids = [row[0] for row in db.execute("SELECT guild_id FROM guild_setups ORDER BY guild_id")]
        return [self.get(guild_id) for guild_id in ids]

    def sheet_owner(self, sheet):
        with self.connect() as db:
            row = db.execute("SELECT guild_id FROM setup_sheet_bindings WHERE sheet_id=?", (sheet,)).fetchone()
        return row[0] if row else None

    def reserve_sheets(self, guild_id, sheets):
        """Réserve les fichiers déjà utilisés par la configuration historique."""
        guild = snowflake(guild_id)
        with self.connect(True) as db:
            for sheet in sheets:
                existing = db.execute("SELECT guild_id FROM setup_sheet_bindings WHERE sheet_id=?", (sheet,)).fetchone()
                if existing and existing[0] != guild:
                    raise SetupConflictError("Un fichier historique est déjà associé à un autre serveur.")
                db.execute("INSERT OR IGNORE INTO setup_sheet_bindings VALUES(?,?)", (sheet, guild))

    @staticmethod
    def _bind_module_sheets(db, guild_id, config):
        for module in ("sales", "machines"):
            block = config.get("modules", {}).get(module)
            if not isinstance(block, dict):
                continue
            mode = storage_mode(config, module)
            bound = db.execute("SELECT mode FROM setup_module_storage WHERE guild_id=? AND module=?", (guild_id, module)).fetchone()
            if bound and bound[0] != mode:
                raise SetupConflictError("Changer le stockage d’une fonction existante nécessite une migration de son historique.")
            db.execute("INSERT OR IGNORE INTO setup_module_storage VALUES(?,?,?)", (guild_id, module, mode))
            if not block.get("sheet_id"):
                continue
            existing = db.execute("SELECT sheet_id FROM setup_module_sheets WHERE guild_id=? AND module=?", (guild_id, module)).fetchone()
            if existing and existing[0] != block["sheet_id"]:
                raise SetupConflictError(
                    "Changer le Google Sheet d’une fonction déjà configurée nécessite une migration "
                    "de son historique. Le classeur actuel est conservé."
                )
            db.execute("INSERT OR IGNORE INTO setup_module_sheets VALUES(?,?,?)", (guild_id, module, block["sheet_id"]))

    def reserve_module_sheets(self, guild_id, modules):
        """Associe les classeurs historiques avant le premier démarrage multi-serveurs."""
        guild = snowflake(guild_id)
        with self.connect(True) as db:
            self._bind_module_sheets(db, guild, {"modules": modules})

    def check_module_sheets(self, guild_id, config):
        """Contrôle en lecture seule ; save répète ce contrôle sous transaction."""
        with self.connect() as db:
            existing = {row["module"]: row["sheet_id"] for row in db.execute(
                "SELECT module,sheet_id FROM setup_module_sheets WHERE guild_id=?", (str(guild_id),))}
            modes = dict(db.execute("SELECT module,mode FROM setup_module_storage WHERE guild_id=?", (str(guild_id),)))
        for module, block in config.get("modules", {}).items():
            if isinstance(block, dict) and module in modes and modes[module] != storage_mode(config, module):
                raise SetupConflictError("Changer le stockage d’une fonction existante nécessite une migration de son historique.")
            if isinstance(block, dict) and block.get("sheet_id") and module in existing and existing[module] != block["sheet_id"]:
                raise SetupConflictError(
                    "Changer le Google Sheet d’une fonction déjà configurée nécessite une migration "
                    "de son historique. Le classeur actuel est conservé."
                )

    def bound_storage(self, guild_id):
        with self.connect() as db:
            return dict(db.execute("SELECT module,mode FROM setup_module_storage WHERE guild_id=?", (str(guild_id),)))

    def save(self, guild_id, config, actor_id, expected_revision=None):
        body = normalize_setup(guild_id, config)
        guild = body["guild_id"]
        at = datetime.now(timezone.utc).isoformat()
        with self.connect(True) as db:
            previous = db.execute("SELECT revision,config FROM guild_setups WHERE guild_id=?", (guild,)).fetchone()
            revision = previous[0] if previous else 0
            if expected_revision is not None and (type(expected_revision) is not int or expected_revision != revision):
                raise SetupConflictError("Le setup a changé. Recharge la page avant d’enregistrer.")
            if previous:
                self._bind_module_sheets(db, guild, json.loads(previous["config"]))
            self._bind_module_sheets(db, guild, body)
            for sheet in setup_sheet_ids(body):
                owner = db.execute("SELECT guild_id FROM setup_sheet_bindings WHERE sheet_id=?", (sheet,)).fetchone()
                if owner and owner[0] != guild:
                    raise SetupConflictError("Ce Google Sheet est déjà réservé à un autre serveur Discord.")
            for sheet in setup_sheet_ids(body):
                # Un ancien classeur contient toujours les données de son serveur.
                # Désactiver une fonction ne l'ouvre pas à un autre Discord.
                db.execute("INSERT OR IGNORE INTO setup_sheet_bindings VALUES(?,?)", (sheet, guild))
            db.execute("INSERT INTO guild_setups VALUES(?,?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET config=excluded.config,revision=excluded.revision,updated_at=excluded.updated_at,actor_id=excluded.actor_id",
                       (guild, json.dumps(body, ensure_ascii=False), revision + 1, at, str(actor_id)))
            db.execute("INSERT INTO setup_audit(guild_id,actor_id,at,kind,detail) VALUES(?,?,?,?,?)",
                       (guild, str(actor_id), at, "setup_saved", json.dumps({"revision": revision + 1, "modules": [key for key, value in body["modules"].items() if value]})))
        return self.get(guild)

    def challenge(self, guild_id, actor_id):
        token = f"discord:{snowflake(guild_id)}:{secrets.token_urlsafe(24)}"
        expires = time.time() + 900
        with self.connect(True) as db:
            db.execute("INSERT OR REPLACE INTO setup_challenges VALUES(?,?,?,?)", (str(guild_id), str(actor_id), token, expires))
        return {"token": token, "worksheet": "Configuration bot", "cell": "A1", "expires_at": expires}

    def current_challenge(self, guild_id, actor_id):
        with self.connect() as db:
            row = db.execute("SELECT token FROM setup_challenges WHERE guild_id=? AND actor_id=? AND expires>?", (str(guild_id), str(actor_id), time.time())).fetchone()
        return row[0] if row else None

    def prove(self, guild_id, actor_id, sheet):
        with self.connect(True) as db:
            db.execute("INSERT OR REPLACE INTO setup_proofs VALUES(?,?,?,?)", (str(guild_id), str(actor_id), sheet, time.time() + 900))

    def has_proof(self, guild_id, actor_id, sheet):
        if self.sheet_owner(sheet) == str(guild_id): return True
        with self.connect() as db:
            return bool(db.execute("SELECT 1 FROM setup_proofs WHERE guild_id=? AND actor_id=? AND sheet_id=? AND expires>?", (str(guild_id), str(actor_id), sheet, time.time())).fetchone())

    def queue_action(self, guild_id, kind, actor_id):
        if kind != "install_panels": raise SetupValidationError("Action Setup inconnue.")
        if not self.get(guild_id): raise SetupValidationError("Enregistre d’abord le setup de ce serveur.")
        with self.connect(True) as db:
            row = db.execute("SELECT id FROM setup_actions WHERE guild_id=? AND kind=? AND completed IS NULL", (str(guild_id), kind)).fetchone()
            if row: return row[0]
            cursor = db.execute("INSERT INTO setup_actions(guild_id,kind,actor_id,created) VALUES(?,?,?,?)", (str(guild_id), kind, str(actor_id), time.time()))
            return cursor.lastrowid

    def pending_actions(self, kind=None):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM setup_actions WHERE completed IS NULL" + (" AND kind=?" if kind else "") + " ORDER BY id LIMIT 100", (kind,) if kind else ()).fetchall()
        return [dict(row) for row in rows]

    def complete_action(self, ident, error=None):
        with self.connect(True) as db:
            db.execute("UPDATE setup_actions SET completed=?,error=? WHERE id=? AND completed IS NULL", (time.time(), str(error)[:500] if error else None, ident))
