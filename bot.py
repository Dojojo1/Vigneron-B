import os
import json
import asyncio
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands
import gspread
from google.oauth2.service_account import Credentials

# =========================
# CONFIGURATION
# =========================
GUILD_ID = 1500958425281204305

SALES_CHANNEL_ID = 1551448652969545839
SALES_CHANNEL_IDS = (SALES_CHANNEL_ID, 1563696678081404989)
MACHINES_CHANNEL_ID = 1551448857378824203
MACHINE_REMINDER_CHANNEL_ID = 1502762441069559869
MACHINE_REMINDER_ROLE_NAME = "Employés"
MACHINE_STATS_CHANNEL_ID = 1554287968229793863
MACHINE_LOGS_CHANNEL_ID = 1554289860355956736
MACHINE_STATS_FILE = Path("machine_weekly_stats.json")
MACHINE_STATS_MESSAGE_LOCK = asyncio.Lock()  # Évite deux nouveaux messages en parallèle.
MACHINE_WEEKLY_RESET_FILE = Path("machine_sheet_weekly_reset.json")

SALE_ADD_ROLES = {1500959983754543144, 1540707610796494950, 1500960060203859989}
SALE_STATUS_ROLES = {1500960060203859989, 1500959983754543144}
MACHINE_ROLES = {1500960060203859989, 1500959983754543144}

TOMBOLA_CHANNEL_ID = 1554294360932356177  # Fiches Tombola publiées
TOMBOLA_PANEL_CHANNEL_ID = 1554462940974030909  # Panneau de gestion
TOMBOLA_ROLES = {1543962159833415710, 1500959983754543144}
TOMBOLA_DATA_FILE = Path("tombola_vehicules.json")
VEHICLE_CATALOG_FILE = Path("vehicules_tombola.json")

SALES_SHEET_ID = "1rCQzFXS9r_cW_kUA-QwpbAjipeZ1r4rp7U8PFBJyX50"
SALES_WORKSHEET = "En cours"
SALES_FIRST_ROW = 10

MACHINES_SHEET_ID = "1TylGS63Wrts7zyJ7ntmJYsuXa4J5Q7bdAkYJBppn8Yk"
MACHINES_WORKSHEET = "Blanchiments"
MACHINES_FIRST_ROW = 8

TIMEZONE = ZoneInfo("Europe/Brussels")
QUEBEC_TIMEZONE = ZoneInfo("America/Toronto")
MACHINE_DURATION = timedelta(hours=4, minutes=45)


def machine_time_shift(value: datetime, elapsed: timedelta) -> datetime:
    """Mesure le temps réel écoulé, y compris pendant un changement d'heure."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=TIMEZONE)
    return (value.astimezone(timezone.utc) + elapsed).astimezone(TIMEZONE)


def machine_display_time(value: datetime) -> str:
    """Affiche le même instant à Bruxelles et au Québec (heure de Montréal)."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=TIMEZONE)
    return (
        value.astimezone(TIMEZONE).strftime("%d/%m/%Y à %H:%M")
        + "\n🇨🇦 Québec : "
        + value.astimezone(QUEBEC_TIMEZONE).strftime("%d/%m/%Y à %H:%M")
    )


MAX_MACHINE_AMOUNT = 1_000_000
DEFAULT_MACHINE_AMOUNT = 1_000_000
MACHINE_HISTORY_DAYS = 365

# Choix disponibles dans les menus Sales
SALE_EMPLOYEES = {
    "Tom Kerrigan 229991": "229991",
    "Donatello 239739": "239739",
    "Lily 315715": "315715",
    "Ekio 222449": "222449",
}
SALE_GROUPS = ["Rubi Oscuro", "Zhovta Krov", "Obscyde"]
SALE_CHOICES_FILE = Path(os.getenv("SALE_CHOICES_FILE", "sale_choices.json"))


def load_sale_choices():
    if not SALE_CHOICES_FILE.exists():
        return
    data = json.loads(SALE_CHOICES_FILE.read_text(encoding="utf-8"))
    # Le fichier contient la liste complète, y compris les suppressions des choix initiaux.
    if "employees" in data:
        SALE_EMPLOYEES.clear()
        SALE_EMPLOYEES.update(data["employees"])
    if "groups" in data:
        SALE_GROUPS[:] = data["groups"]


def save_sale_choices(employees, groups):
    tmp = SALE_CHOICES_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"employees": employees, "groups": groups},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SALE_CHOICES_FILE)


REMINDERS_FILE = Path(os.getenv("REMINDERS_FILE", "machine_reminders.json"))
WEEKLY_RESET_FILE = Path(os.getenv("WEEKLY_RESET_FILE", "weekly_sales_reset.json"))
SALE_MESSAGES_FILE = Path(os.getenv("SALE_MESSAGES_FILE", "sale_messages.json"))
# Avancement Discord seulement : ne change AUCUNE cellule du Google Sheets Suivi.
SALE_PROGRESS_FILE = Path(os.getenv("SALE_PROGRESS_FILE", "sale_progress_weekly.json"))
RUBI_OSCURO_MENTION_ID = os.getenv("RUBI_OSCURO_MENTION_ID", "").strip()

SALE_ACTIVE_DAYS = 365
# La première migration examine les anciennes fiches une fois, puis seulement 365 jours.
SALE_HISTORY_MIGRATION_FILE = Path(os.getenv("SALE_HISTORY_MIGRATION_FILE", "sale_history_365d_migrated.flag"))
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "google_credentials.json")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Each guild runtime executes these definitions with its validated setup and
# independent handler globals. The gateway client itself remains shared.
_tenant_runtime_active_modules = {"sales", "machines", "tombola"}
if globals().get("_guild_runtime_overrides"):
    globals().update(_guild_runtime_overrides)
else:
    load_sale_choices()

# =========================
# GOOGLE SHEETS
# =========================
_GSPREAD_CLIENT = None

def uses_local_storage(module):
    return globals().get("_tenant_storage_modes", {}).get(module, globals().get("_tenant_storage_mode")) == "local"

def get_gspread_client():
    """Réutilise la même connexion Google au lieu de la recréer à chaque opération."""
    global _GSPREAD_CLIENT
    if _GSPREAD_CLIENT is None:
        def google_client():
            credentials = Credentials.from_service_account_file(GOOGLE_CREDENTIALS, scopes=SCOPES)
            return gspread.authorize(credentials)
        books = {value: name for value,name in ((SALES_SHEET_ID,"sales"),(MACHINES_SHEET_ID,"machines"))
                 if value and uses_local_storage(name)}
        if books:
            from local_workbooks import LocalWorkbookClient, RoutingWorkbookClient
            local = LocalWorkbookClient(globals()["_tenant_local_store"], books)
            google_ids = {value for value in (SALES_SHEET_ID, MACHINES_SHEET_ID) if value and value not in books}
            _GSPREAD_CLIENT = RoutingWorkbookClient(local, google_ids, google_client)
        else:
            _GSPREAD_CLIENT = google_client()
    runtime = globals().get("_tenant_bot_facade")
    return runtime.google_client(_GSPREAD_CLIENT) if runtime is not None else _GSPREAD_CLIENT

def worksheet(sheet_id: str, worksheet_name: str):
    # Ne pas mettre les worksheets en cache :
    # les resets hebdomadaires renomment et recréent certaines feuilles.
    return get_gspread_client().open_by_key(sheet_id).worksheet(worksheet_name)

def next_free_row(ws, check_column: int, first_row: int) -> int:
    """Returns the first empty row from first_row downward in check_column."""
    values = ws.col_values(check_column)
    row = first_row
    while row <= len(values) and str(values[row - 1]).strip():
        row += 1
    return row

async def run_blocking(func, *args):
    return await asyncio.to_thread(func, *args)


def parse_sale_date(raw_date: str) -> str:
    """Accepte JJ/MM (année de Bruxelles) ou JJ/MM/AAAA, avec validation réelle."""
    value = str(raw_date).strip()
    if not re.fullmatch(r"\d{1,2}/\d{1,2}(?:/\d{4})?", value):
        raise ValueError("Utilise JJ/MM ou JJ/MM/AAAA (exemple : 03/10).")
    if value.count("/") == 1:
        value = f"{value}/{datetime.now(TIMEZONE).year}"
    try:
        return datetime.strptime(value, "%d/%m/%Y").strftime("%d/%m/%Y")
    except ValueError as exc:
        raise ValueError("Date impossible. Utilise JJ/MM ou JJ/MM/AAAA.") from exc


def sale_embed_field(message, name: str, default: str = "") -> str:
    if message.embeds:
        for field in message.embeds[0].fields:
            if field.name == name:
                return str(field.value).strip().replace("**", "")
    return default


def upsert_sale_embed_field(embed, name: str, value: str, inline: bool = True):
    """Modifie le champ existant au lieu de créer des doublons."""
    for index, field in enumerate(embed.fields):
        if field.name == name:
            embed.set_field_at(index, name=name, value=value, inline=inline)
            return
    embed.add_field(name=name, value=value, inline=inline)


def normalize_sale_employee(value: str) -> str:
    """Accepte le nom complet, le prénom unique ou l'ID de l'employé."""
    raw = str(value).strip().casefold()
    if not raw:
        raise ValueError("L'employé est obligatoire.")
    exact = [name for name, uid in SALE_EMPLOYEES.items()
             if raw in {name.casefold(), uid.casefold(), name.rsplit(" ", 1)[0].casefold()}]
    if len(exact) == 1:
        return exact[0]
    prefix = [name for name in SALE_EMPLOYEES if name.casefold().startswith(raw)]
    if len(prefix) == 1:
        return prefix[0]
    raise ValueError("Employé inconnu ou ambigu. Choisis : " + ", ".join(SALE_EMPLOYEES))


def normalize_sale_group(value: str) -> str:
    raw = str(value).strip().casefold()
    matches = [name for name in SALE_GROUPS if name.casefold() == raw]
    if not matches:
        matches = [name for name in SALE_GROUPS if name.casefold().startswith(raw) and raw]
    if len(matches) == 1:
        return matches[0]
    raise ValueError("Groupe inconnu. Choisis : " + " / ".join(SALE_GROUPS))

def load_sale_messages():
    """Association persistante message Discord -> feuille/ligne Google Sheets."""
    if not SALE_MESSAGES_FILE.exists():
        return {}
    try:
        data = json.loads(SALE_MESSAGES_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        print(f"[SALE] Impossible de lire {SALE_MESSAGES_FILE}: {exc}")
        return {}


def save_sale_messages(data: dict):
    tmp = SALE_MESSAGES_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SALE_MESSAGES_FILE)


def sale_is_expired(message, now=None):
    """Délai calculé depuis la création réelle du message Discord, pas la date Sheet."""
    created_at = message.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if now is None:
        now = datetime.now(timezone.utc)
    return now - created_at >= timedelta(days=SALE_ACTIVE_DAYS)


def sale_record_is_expired(record, now=None):
    """Les anciens enregistrements sans date sont vérifiés via Discord."""
    if not isinstance(record, dict) or not record.get("created_at"):
        return False
    try:
        created_at = datetime.fromisoformat(record["created_at"])
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return (now or datetime.now(timezone.utc)) - created_at >= timedelta(days=SALE_ACTIVE_DAYS)
    except (ValueError, TypeError):
        return False


def sale_fingerprint(message):
    """Champs immuables de la fiche; le statut et la date de rendu sont ignorés."""
    if not message.embeds:
        return {}
    fields = {field.name: str(field.value).strip() for field in message.embeds[0].fields}
    result = {}
    names = {
        "date": ("📅 Date reçu", "📅 Date"),
        "group": ("🏴 Groupe",),
        "employee": ("👤 Employé",),
        "giver": ("🪪 Joueur qui donne", "👤 Qui / ID"),
        "amount": ("💰 Somme à blanchir",),
    }
    for key, alternatives in names.items():
        value = next((fields[name] for name in alternatives if name in fields), "")
        if not value:
            continue
        if key in {"amount", "giver"}:
            value = re.sub(r"\D", "", value)
        elif key in {"group", "employee"}:
            value = value.casefold().strip()
        if value:
            result[key] = value
    return result


def sale_row_matches(row_values, fingerprint: dict):
    """Empêche qu'une ancienne fiche écrase une nouvelle vente sur la même ligne."""
    if len(fingerprint) < 2:
        return False
    cells = list(row_values) + [""] * max(0, 8 - len(row_values))
    actual = {
        "date": str(cells[1]).strip(),  # C
        "group": str(cells[3]).casefold().strip(),  # E
        "employee": str(cells[4]).casefold().strip(),  # F
        "giver": re.sub(r"\D", "", str(cells[5])),  # G
        "amount": re.sub(r"\D", "", str(cells[7])),  # I
    }
    return all(actual.get(key) == value for key, value in fingerprint.items())


def sale_message_row(message):
    """Compatible avec les fiches anciennes, même si leur libellé a changé."""
    if message.embeds:
        title = message.embeds[0].title or ""
        match = re.search(r"\bLigne\s+(\d+)\b", title, re.IGNORECASE)
        if match and "SALE" in title.upper():
            return int(match.group(1))
    for action_row in message.components:
        for component in getattr(action_row, "children", []):
            custom_id = getattr(component, "custom_id", "") or ""
            match = re.fullmatch(r"sale_(?:waiting|progress|finished|add_new|reset_week|edit|cancel):(\d+)", custom_id)
            if match:
                return int(match.group(1))
    return None


def register_sale_message(message, row: int, worksheet_name: str | None,
                          creator_id: int | None = None):
    """Conserve l'auteur et le statut annulé lors des mises à jour d'une fiche."""
    data = load_sale_messages()
    previous = data.get(str(message.id), {})
    record = dict(previous) if isinstance(previous, dict) else {}
    record.update({
        "row": int(row),
        "worksheet": worksheet_name,
        "fingerprint": sale_fingerprint(message),
        "created_at": message.created_at.isoformat(),
    })
    if creator_id is not None:
        record["creator_id"] = int(creator_id)
    data[str(message.id)] = record
    save_sale_messages(data)


def sale_is_cancelled(message_id: int) -> bool:
    record = load_sale_messages().get(str(message_id), {})
    return isinstance(record, dict) and bool(record.get("cancelled", False))


def sale_can_correct(member, message_id: int) -> bool:
    """Un responsable peut corriger toutes les fiches ; l'auteur, la sienne."""
    if not isinstance(member, discord.Member):
        return False
    if has_role(member, SALE_STATUS_ROLES):
        return True
    if not has_role(member, SALE_ADD_ROLES):
        return False
    record = load_sale_messages().get(str(message_id), {})
    return isinstance(record, dict) and record.get("creator_id") == member.id


def mark_sale_cancelled(message_id: int, member_id: int):
    data = load_sale_messages()
    record = data.get(str(message_id))
    if not isinstance(record, dict):
        raise LookupError("Association de la fiche introuvable : annulation non enregistrée.")
    record["cancelled"] = True
    record["cancelled_by"] = int(member_id)
    record["cancelled_at"] = datetime.now(timezone.utc).isoformat()
    save_sale_messages(data)


def archive_sale_message_records(archive_name: str):
    """Le reset renomme En cours : les anciennes fiches doivent viser l'archive."""
    data = load_sale_messages()
    changed = 0
    for record in data.values():
        if isinstance(record, dict) and record.get("worksheet") == SALES_WORKSHEET:
            record["worksheet"] = archive_name
            changed += 1
    if changed:
        save_sale_messages(data)
    print(f"[SALE] Reset : {changed} fiche(s) reliée(s) à l'archive {archive_name}.")


def find_sale_worksheet(message, row: int):
    """Vérifie la ligne avant toute écriture; retrouve aussi les anciennes archives."""
    fingerprint = sale_fingerprint(message)
    if len(fingerprint) < 2:
        raise LookupError("Cette ancienne fiche ne contient pas assez d'informations pour identifier sa ligne Google Sheets.")

    book = get_gspread_client().open_by_key(SALES_SHEET_ID)
    sheets = [ws for ws in book.worksheets()
              if ws.title == SALES_WORKSHEET or re.fullmatch(r"s\d+", ws.title, re.IGNORECASE)]
    record = load_sale_messages().get(str(message.id), {})
    recorded_name = record.get("worksheet") if isinstance(record, dict) and record.get("row") == row else None
    # Les fiches créées avec cette version sont retrouvées en une seule lecture.
    if recorded_name:
        recorded_ws = next((ws for ws in sheets if ws.title == recorded_name), None)
        if recorded_ws is not None:
            values = recorded_ws.get(f"B{row}:I{row}")
            if values and sale_row_matches(values[0], fingerprint):
                return recorded_name

    # Pour les fiches plus anciennes, Google permet de lire toutes les archives
    # en UNE requête plutôt que de dépasser le quota avec 40+ lectures.
    ranges = [f"'{ws.title}'!B{row}:I{row}" for ws in sheets]
    try:
        response = book.values_batch_get(ranges=ranges)
        value_ranges = response.get("valueRanges", [])
        if len(value_ranges) != len(sheets):
            raise LookupError("Google Sheets n'a pas retourné toutes les feuilles demandées.")
        candidates = [(ws.title, item.get("values", []))
                      for ws, item in zip(sheets, value_ranges)]
    except (AttributeError, TypeError):
        # Compatibilité avec les versions de gspread sans values_batch_get.
        candidates = [(ws.title, ws.get(f"B{row}:I{row}")) for ws in sheets]

    matches = [name for name, values in candidates
               if values and sale_row_matches(values[0], fingerprint)]

    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise LookupError(
            "Aucune ligne correspondante dans En cours ou les archives. "
            "La fiche n'a pas été modifiée pour éviter d'écraser un autre sale."
        )
    raise LookupError(
        "Plusieurs lignes identiques existent dans les archives. "
        "Impossible de choisir la bonne feuille sans risque."
    )


async def resolve_sale_worksheet(message, row: int):
    # Vérification à l'écriture : un vieux bouton ou un formulaire déjà ouvert
    # ne peut jamais modifier une fiche après son expiration.
    if sale_is_expired(message):
        raise LookupError("Cette fiche a expiré après 365 jours. Son historique reste consultable.")
    if sale_is_cancelled(message.id):
        raise LookupError("Ce sale a été annulé : ses données ne peuvent plus être modifiées.")
    worksheet_name = await run_blocking(find_sale_worksheet, message, row)
    data = load_sale_messages()
    if (data.get(str(message.id), {}).get("worksheet") != worksheet_name
            or data.get(str(message.id), {}).get("row") != row):
        register_sale_message(message, row, worksheet_name)
    return worksheet_name


def add_sale_to_sheet(date_text: str, group: str, employee: str, giver_id: str, amount: int):
    ws = worksheet(SALES_SHEET_ID, SALES_WORKSHEET)
    if uses_local_storage("sales"):
        return ws.append_record({"B":"en attente","C":date_text,"E":group,"F":employee,"G":int(giver_id),"I":amount}, SALES_FIRST_ROW)
    # Une entrée de sale occupe une ligne dès que la colonne B contient un état.
    row = next_free_row(ws, 2, SALES_FIRST_ROW)
    ws.batch_update([
        {"range": f"B{row}", "values": [["en attente"]]},
        {"range": f"C{row}", "values": [[date_text]]},
        {"range": f"D{row}", "values": [[""]]},
        {"range": f"E{row}", "values": [[group]]},
        {"range": f"F{row}", "values": [[employee]]},
        {"range": f"G{row}", "values": [[int(giver_id)]]},
        {"range": f"H{row}", "values": [[""]]},
        {"range": f"I{row}", "values": [[amount]]},
    ])
    return row

def reset_sales_week_sheet():
    """Archive `En cours` to the next sXX sheet and recreate a clean `En cours`."""
    gc = get_gspread_client()
    book = gc.open_by_key(SALES_SHEET_ID)
    if uses_local_storage("sales"):
        archive_name = book.archive("sales", datetime.now(TIMEZONE).isocalendar().week)
        archive_sale_message_records(archive_name)
        return archive_name
    current = book.worksheet(SALES_WORKSHEET)

    # Find the highest existing archive number (s39 -> next is s40).
    archive_numbers = []
    for ws in book.worksheets():
        title = ws.title.strip()
        if len(title) >= 2 and title[0].lower() == "s" and title[1:].isdigit():
            archive_numbers.append(int(title[1:]))

    if archive_numbers:
        next_number = max(archive_numbers) + 1
    else:
        # First ever reset: use the current ISO week number.
        next_number = datetime.now(TIMEZONE).isocalendar().week

    archive_name = f"s{next_number}"
    existing_titles = {ws.title for ws in book.worksheets()}
    while archive_name in existing_titles:
        next_number += 1
        archive_name = f"s{next_number}"

    # Archive the finished week.
    current.update_title(archive_name)

    # Start the new week from the dedicated template.
    model = book.worksheet("Modele")
    model.duplicate(new_sheet_name=SALES_WORKSHEET)

    try:
        archive_sale_message_records(archive_name)
    except Exception as exc:
        # L'archivage Google a déjà réussi : ne jamais relancer le reset pour
        # un simple problème d'écriture du fichier local.
        print(f"[SALE] Archive {archive_name} créée, sauvegarde locale impossible : {exc}")
    return archive_name

def edit_sale_sheet(row: int, date_text: str, group: str, employee: str,
                    giver_id: str, amount: int, worksheet_name: str):
    """Corrige seulement les champs de création, sans toucher au statut/rendu."""
    ws = worksheet(SALES_SHEET_ID, worksheet_name)
    ws.batch_update([
        {"range": f"C{row}", "values": [[date_text]]},
        {"range": f"E{row}", "values": [[group]]},
        {"range": f"F{row}", "values": [[employee]]},
        {"range": f"G{row}", "values": [[int(giver_id)]]},
        {"range": f"I{row}", "values": [[amount]]},
    ])


def cancel_sale_sheet(row: int, worksheet_name: str):
    """Efface TOUTES les données du sale, sans décaler les autres fiches.

    Une suppression physique avec delete_rows() déplacerait les numéros des
    autres sales et rendrait leurs anciens boutons Discord incorrects.
    """
    ws = worksheet(SALES_SHEET_ID, worksheet_name)
    ws.batch_clear([f"B{row}:I{row}"])


def update_sale_status_sheet(row: int, status: str, worksheet_name: str = SALES_WORKSHEET):
    ws = worksheet(SALES_SHEET_ID, worksheet_name)
    ws.update_acell(f"B{row}", status)

def finish_sale_sheet(row: int, receiver: str, returned_date: str, worksheet_name: str = SALES_WORKSHEET):
    ws = worksheet(SALES_SHEET_ID, worksheet_name)
    ws.batch_update([
        {"range": f"B{row}", "values": [["Terminé"]]},
        {"range": f"D{row}", "values": [[returned_date]]},
        {"range": f"H{row}", "values": [[int(receiver)]]},
    ])

def add_machine_to_sheet(date_text: str, time_text: str, amount: int, launched_by: str):
    ws = worksheet(MACHINES_SHEET_ID, MACHINES_WORKSHEET)
    if uses_local_storage("machines"):
        return ws.append_record({"B":date_text,"C":amount,"E":time_text,"H":launched_by}, MACHINES_FIRST_ROW)
    # Column B is the main occupancy column for machines.
    row = next_free_row(ws, 2, MACHINES_FIRST_ROW)
    ws.batch_update([
        {"range": f"B{row}", "values": [[date_text]]},
        {"range": f"C{row}", "values": [[amount]]},
        {"range": f"E{row}", "values": [[time_text]]},
        {"range": f"H{row}", "values": [[launched_by]]},
    ])
    return row

def update_machine_time_sheet(row: int, time_text: str, date_text: str):
    """Met à jour la date et l'heure sans toucher aux formules."""
    ws = worksheet(MACHINES_SHEET_ID, MACHINES_WORKSHEET)
    ws.batch_update([
        {"range": f"B{int(row)}", "values": [[date_text]]},
        {"range": f"E{int(row)}", "values": [[time_text]]},
    ])


def reset_machines_week_sheet():
    """
    Reproduit le script Google Apps Script :
    - copie Blanchiments vers Semaine X+1
    - place la copie à la fin
    - nettoie B8:B166, C8:C174, E8:E174, H8:H174, P1:P210 et D3
    """
    gc = get_gspread_client()
    book = gc.open_by_key(MACHINES_SHEET_ID)
    if uses_local_storage("machines"):
        return book.archive("machines")
    source = book.worksheet(MACHINES_WORKSHEET)

    max_week = 0
    for ws in book.worksheets():
        title = ws.title.strip()
        if title.startswith("Semaine "):
            number = title[len("Semaine "):].strip()
            if number.isdigit():
                max_week = max(max_week, int(number))

    new_name = f"Semaine {max_week + 1}"

    # Copie AVANT nettoyage afin de conserver l'historique complet.
    copy = source.duplicate(
        insert_sheet_index=len(book.worksheets()),
        new_sheet_name=new_name
    )

    # Nettoyage après archivage : efface aussi les anciennes dates (colonne B).
    # La colonne D contient les formules et ne doit pas être vidée, sauf D3 déjà prévu.
    source.batch_clear([
        "B8:B166",
        "C8:C174",
        "E8:E174",
        "H8:H174",
        "P1:P210",
        "D3",
    ])

    return new_name


def load_machine_weekly_reset_state():
    if not MACHINE_WEEKLY_RESET_FILE.exists():
        return {}
    try:
        data = json.loads(MACHINE_WEEKLY_RESET_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_machine_weekly_reset_state(week_start: str, archive_name: str):
    tmp = MACHINE_WEEKLY_RESET_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(
            {"week_start": week_start, "archive": archive_name},
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )
    tmp.replace(MACHINE_WEEKLY_RESET_FILE)


async def reset_machine_week_everything(*, manual=False):
    """Archive le Sheet et crée un nouveau classement sans toucher à l'ancien.

    Une seule archive Sheet par semaine, même après redémarrage. Un reset manuel
    peut aussi ouvrir un nouveau classement dans la même semaine.
    """
    week = current_week_start()
    state = load_machine_weekly_reset_state()

    if state.get("week_start") == week:
        return None, False

    archive_name = await run_blocking(reset_machines_week_sheet)

    stats = load_machine_stats()
    previous_report = None
    if stats.get("week_start") != week or manual:
        stats, previous_report = start_new_machine_stats_report(
            stats, week, force=manual
        )
        save_machine_stats(stats)

    # Marquer le reset Sheet comme effectué AVANT les appels réseau Discord.
    # Une panne de Discord ne doit pas provoquer une seconde archive Sheet.
    save_machine_weekly_reset_state(week, archive_name)

    if previous_report:
        await finalize_machine_stats_archive(previous_report)

    try:
        await update_machine_stats_message()
    except Exception as exc:
        # Le worker réessaiera de publier le nouveau message si besoin.
        print(f"[MACHINES] Classement de la nouvelle semaine à republier : {exc}")

    try:
        await send_machine_log(
            f"🔄 **Reset hebdomadaire Machines**\n"
            f"📁 Archive créée : **{archive_name}**\n"
            f"🧹 Feuille **{MACHINES_WORKSHEET}** nettoyée\n"
            f"📊 Ancien classement conservé ; nouveau message hebdomadaire créé\n"
            f"🕒 Heure : **{datetime.now(TIMEZONE).strftime('%d/%m/%Y %H:%M:%S')}**"
        )
    except Exception as exc:
        print(f"[MACHINES] Log du reset non envoyé : {exc}")
    return archive_name, True


# =========================
# HELPERS
# =========================
def has_role(member: discord.Member, allowed_roles: set[int]) -> bool:
    return any(role.id in allowed_roles for role in member.roles)

def display_name(member: discord.Member) -> str:
    return member.display_name

def format_money(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " $"

def load_reminders():
    if not REMINDERS_FILE.exists():
        return []
    try:
        data = json.loads(REMINDERS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []

def save_reminders(reminders):
    tmp = REMINDERS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(reminders, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(REMINDERS_FILE)


def cleanup_recovered_machine_reminders():
    """Conserve l'historique récupéré : indispensable aux progressions Sales.

    Cette fonction historique ne doit plus effacer des machines déjà comptées.
    Une récupération est un événement comptable et doit rester disponible même
    si les rappels Discord correspondants ne sont plus utiles.
    """
    print("[MACHINES] Historique des machines récupérées conservé (progression Sales).")
    return 0

def load_weekly_reset_state():
    if not WEEKLY_RESET_FILE.exists():
        return {}
    try:
        data = json.loads(WEEKLY_RESET_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def publish_sales_reset_site_state(data: dict):
    """Signal public minimal : aucun montant, joueur, identifiant Discord ou secret."""
    public_file = globals().get("_tenant_public_reset_file") or Path(__file__).resolve().parent / "site" / "sales-reset-state.json"
    if not public_file.parent.is_dir():
        return
    events = [
        {"id": entry["id"], "at": entry["at"], "mode": entry["mode"]}
        for entry in data.get("site_resets", [])
        if isinstance(entry, dict)
        and all(isinstance(entry.get(key), str) for key in ("id", "at", "mode"))
        and entry["mode"] in ("automatic", "manual")
    ][-104:]
    public = {
        "version": 1,
        "timeZone": "Europe/Brussels",
        "schedule": {"weekday": 0, "hour": 0},
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "events": events,
    }
    tmp = public_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(public_file)


def save_weekly_reset_state(date_text: str, archive_name: str, *, automatic: bool = False):
    reset_at = datetime.now(timezone.utc).isoformat()
    previous = load_weekly_reset_state()
    history = previous.get("site_resets", [])
    if not isinstance(history, list):
        history = []
    history = [*history, {
        "id": f"{reset_at}:{archive_name}",
        "at": reset_at,
        "mode": "automatic" if automatic else "manual",
    }][-104:]
    data = {"last_reset_date": date_text, "archive": archive_name,
            "reset_at": reset_at, "site_resets": history}
    tmp = WEEKLY_RESET_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(WEEKLY_RESET_FILE)
    try:
        publish_sales_reset_site_state(data)
    except Exception as exc:
        # Le reset du bot est déjà mémorisé : ne pas le répéter si le site est indisponible.
        print(f"[SALE] Signal du reset pour le site à republier : {exc}")

# =========================
# PROGRESSION SALE / MACHINES (Discord seulement) • V17.7
# =========================
# IMPORTANT : le bouton historique Terminer demande un destinataire ET renseigne
# une date de restitution dans le Sheet. Une récupération de machine ne prouve
# pas une restitution : on ne déclenche donc PAS cette écriture automatiquement.

SALE_PROGRESS_FIELD = "📊 Progression du blanchiment"
SALE_PROGRESS_DONE_FIELD = "💰 Montant blanchi"
SALE_PROGRESS_LEFT_FIELD = "📦 Reste à blanchir"
# Vérification de secours toutes les 4 heures. Les clics machine déclenchent une mise à jour immédiate.
SALE_PROGRESS_REFRESH_SECONDS = 4 * 60 * 60
_sale_progress_lock = asyncio.Lock()
_sale_progress_last_missing_date = None
_sale_progress_last_unallocated = None
_sale_progress_last_signature = None
_sale_progress_sale_history_ready = asyncio.Event()
_sale_progress_machine_history_ready = asyncio.Event()


def sale_progress_week_key(now=None):
    current = (now or datetime.now(TIMEZONE)).astimezone(TIMEZONE)
    monday = current.date() - timedelta(days=current.weekday())
    return monday.isoformat()


def sale_progress_datetime(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value))
        if result.tzinfo is None:
            return None  # Une date naïve est ambiguë pour les changements d'heure.
        return result.astimezone(TIMEZONE)
    except (ValueError, TypeError, OverflowError):
        return None


def sale_progress_recovered_machines(reminders, week, *, first_open_at=None):
    """Récupérations prises en compte pour les sales encore ouverts.

    `first_open_at` empêche que les récupérations d'avant le premier sale
    encore ouvert soient détournées vers ce sale après un reset hebdomadaire.

    Les anciennes machines déjà marquées récupérées peuvent ne PAS avoir de
    recovered_at (anciennes versions). Si elles ont été lancées APRÈS la
    création du premier sale ouvert, elles ont forcément été récupérées après
    ce lancement : on peut donc les prendre en compte sans inventer une date.
    Sinon elles restent incertaines et ne sont pas imputées arbitrairement.
    """
    cutoff = datetime.fromisoformat(week).replace(tzinfo=TIMEZONE)
    if first_open_at is not None:
        first_open_at = sale_progress_datetime(first_open_at.isoformat())
        if first_open_at is not None and first_open_at > cutoff:
            cutoff = first_open_at
    now = datetime.now(TIMEZONE)
    amounts = {}
    uncertain = 0
    inferred = 0
    # Ne compter QUE les machines réellement marquées « Récupérée » :
    # une machine lancée, terminée par le minuteur ou encore en cours = 0 $.
    # En cas de doublon historique sur un même ID, le dernier état fait foi.
    latest_by_id = {}
    for reminder in reminders:
        if isinstance(reminder, dict):
            machine_id = str(reminder.get("id") or "").strip()
            if machine_id:
                latest_by_id[machine_id] = reminder
    for machine_id, reminder in latest_by_id.items():
        if (reminder.get("recovered") is not True
                or reminder.get("cancelled") or reminder.get("is_test")):
            continue
        try:
            amount = int(reminder.get("amount", 0))
        except (ValueError, TypeError):
            continue
        if amount <= 0:
            continue
        recovered = sale_progress_datetime(reminder.get("recovered_at"))
        launched = sale_progress_datetime(reminder.get("launched_at"))
        if recovered is not None:
            if recovered < cutoff or recovered > now + timedelta(minutes=2):
                continue
            if launched is not None and launched > recovered:
                uncertain += 1
                continue
        else:
            # Recupération historique sans horodatage : validable uniquement
            # si la machine a été lancée après le début du sale à traiter.
            if launched is None:
                uncertain += 1
                continue
            if launched < cutoff:
                # Pour une ancienne machine, on ne sait pas si la récupération
                # a eu lieu avant ou après la création du sale actif.
                if launched >= datetime.fromisoformat(week).replace(tzinfo=TIMEZONE):
                    uncertain += 1
                continue
            if launched > now + timedelta(minutes=2):
                uncertain += 1
                continue
            inferred += 1
        amounts[machine_id] = amount  # ID unique : aucun double décompte.
    if inferred:
        print(f"[PROGRESSION SALE] {inferred} ancienne(s) machine(s) récupérée(s) "
              "sans horodatage, retenue(s) grâce à leur lancement postérieur "
              "au premier sale encore ouvert.")
    return amounts, uncertain


def sale_progress_allocate(sales, machines):
    """FIFO global, sans attribuer deux fois le même euro, calcul déterministe.

    Les ventes terminées manuellement occupent toujours leur place historique dans
    la file, sinon leurs machines seraient attribuées au sale suivant par erreur.
    """
    remaining_pool = sum(max(0, int(v)) for v in machines.values())
    result = []
    for sale in sorted(sales, key=lambda x: (x["created_at"], int(x["message_id"]))):
        amount = max(0, int(sale["amount"]))
        # Une correction manuelle consomme le crédit retiré une seule fois.
        # Il ne doit ni réapparaître au recalcul, ni être transféré au sale suivant.
        deduction = max(0, int(sale.get("progress_deduction", 0)))
        remaining_pool -= min(deduction, remaining_pool)
        treated = min(amount, remaining_pool)
        remaining_pool -= treated
        result.append({**sale, "treated": treated, "remaining": amount - treated})
    return result, remaining_pool


def sale_progress_load_state(week):
    """Garde les fils/notifications par ID de fiche lors d'un changement de semaine.

    Compatible avec l'ancien fichier V17.4 qui contenait une clé `week`.
    """
    try:
        data = json.loads(SALE_PROGRESS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("notifications"), dict):
            state = {"week": week, "notifications": data["notifications"]}
            if isinstance(data.get("cohort"), dict):
                state["cohort"] = data["cohort"]
            return state
    except (OSError, ValueError, TypeError):
        pass
    return {"week": week, "notifications": {}}


def sale_progress_save_state(data):
    tmp = SALE_PROGRESS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SALE_PROGRESS_FILE)


def sale_progress_sale_start(message):
    """Date du sale : priorité au jour déclaré, pas à la semaine du message.

    Si la fiche a été enregistrée le lundi avec « Date reçu = dimanche »,
    il faut aussi voir les machines du dimanche. La date seule ne donne pas
    l'heure ; un contrôle manuel peut être nécessaire pour les machines
    récupérées plus tôt le jour de réception.
    """
    created = sale_progress_datetime(message.created_at.isoformat())
    raw = sale_embed_field(message, "📅 Date reçu", sale_embed_field(message, "📅 Date"))
    if created is None:
        return message.created_at
    try:
        day = datetime.strptime(raw.strip(), "%d/%m/%Y").date()
        received = datetime(day.year, day.month, day.day, tzinfo=TIMEZONE)
        if received <= created and (created - received) <= timedelta(days=60):
            return received
    except (ValueError, TypeError, AttributeError):
        pass
    return created


def sale_progress_embed_amount(message):
    raw = sale_embed_field(message, "💰 Somme à blanchir")
    digits = re.sub(r"\D", "", raw)
    return int(digits) if digits else 0


def sale_progress_is_cancelled(message):
    status = sale_embed_field(message, "📌 Statut").upper()
    return "ANNUL" in status or sale_is_cancelled(message.id)


def sale_progress_is_manual_finished(message):
    """Le bouton manuel ajoute le destinataire ou la date de rendu."""
    return bool(sale_embed_field(message, "📦 Joueur qui récupère")
                or sale_embed_field(message, "📅 Date rendu"))


def sale_progress_upsert_if_changed(embed, name, value, inline):
    for index, field in enumerate(embed.fields):
        if field.name == name:
            if field.value == value and field.inline == inline:
                return False
            embed.set_field_at(index, name=name, value=value, inline=inline)
            return True
    if len(embed.fields) >= 25:
        raise ValueError("Embed Discord trop chargé pour ajouter la progression")
    embed.add_field(name=name, value=value, inline=inline)
    return True


def sale_progress_update_embed(message, treated, amount):
    embed = message.embeds[0].copy()
    remaining = max(0, amount - treated)
    percentage = int(100 * treated / amount) if amount else 0
    filled = min(10, percentage // 10)
    bar = "🟩" * filled + "⬜" * (10 - filled)
    display = f"{bar} **{percentage} %**"
    changed = sale_progress_upsert_if_changed(embed, SALE_PROGRESS_FIELD, display, False)
    changed |= sale_progress_upsert_if_changed(
        embed, SALE_PROGRESS_DONE_FIELD, f"**{format_money(treated)}**", True
    )
    changed |= sale_progress_upsert_if_changed(
        embed, SALE_PROGRESS_LEFT_FIELD, f"**{format_money(remaining)}**", True
    )
    # Ne jamais écraser un sale terminé MANUELLEMENT, car sa restitution est réelle.
    if not sale_progress_is_fully_finished(message):
        previous = sale_embed_field(message, "📌 Statut").upper()
        if remaining == 0 and amount > 0:
            status = "🟢 **BLANCHIMENT TERMINÉ • RESTITUTION À CONFIRMER**"
            changed |= sale_progress_upsert_if_changed(embed, "📌 Statut", status, False)
        elif "BLANCHIMENT TERMINÉ" in previous:
            # Une machine repassée Non récupérée doit corriger l'embed.
            status = "🔵 **EN COURS**" if treated else "🟡 **EN ATTENTE**"
            changed |= sale_progress_upsert_if_changed(embed, "📌 Statut", status, False)
    return embed, changed


def sale_progress_rubi_ping(guild):
    """Priorité au véritable ID configuré ; fallback sur rôle exact du serveur."""
    if RUBI_OSCURO_MENTION_ID.isdigit():
        ident = int(RUBI_OSCURO_MENTION_ID)
        role = guild.get_role(ident) if guild else None
        if role:
            return role.mention
        member = guild.get_member(ident) if guild else None
        if member:
            return member.mention
    if guild:
        role = next((role for role in guild.roles
                     if role.name.casefold().strip() == "rubi oscuro"), None)
        if role:
            return role.mention
    return None


async def sale_progress_announce(message, sale, state, *, complete):
    """Un seul fil par sale ; transitions enregistrées pour éviter les doublons."""
    key = str(message.id)
    notifications = state["notifications"]
    record = notifications.setdefault(key, {})
    if bool(record.get("complete", False)) == bool(complete):
        return
    if not complete and not record.get("thread_id"):
        record["complete"] = False
        sale_progress_save_state(state)
        return
    thread = None
    try:
        if record.get("thread_id"):
            thread = message.guild.get_thread(int(record["thread_id"]))
            if thread is None:
                thread = await bot.fetch_channel(int(record["thread_id"]))
        else:
            row = sale["row"]
            thread = await message.create_thread(name=f"Blanchiment • Ligne {row}")
            record["thread_id"] = str(thread.id)
            sale_progress_save_state(state)
        if not isinstance(thread, discord.Thread):
            raise ValueError("Le canal de notification doit être un fil Discord.")
        if thread.archived:
            await thread.edit(archived=False)
        if complete:
            ping = sale_progress_rubi_ping(message.guild)
            text = (
                f"{ping + chr(10) if ping else ''}"
                "✅ **Blanchiment entièrement terminé !**\n"
                f"📋 Sale ligne **{sale['row']}** • Groupe : **{sale['group']}**\n"
                f"💰 Montant blanchi : **{format_money(sale['amount'])}**\n"
                "📦 **La restitution reste à confirmer** avec le bouton « Terminer » "
                "de la fiche."
            )
        else:
            text = (
                "⚠️ **Correction du suivi** : une machine est repassée « Non récupérée » "
                "ou a été annulée. Le sale n'est plus intégralement blanchi. "
                "La progression de sa fiche a été corrigée."
            )
        await thread.send(
            text, allowed_mentions=discord.AllowedMentions(users=True, roles=True)
        )
        record["complete"] = bool(complete)
        sale_progress_save_state(state)
    except (discord.Forbidden, discord.HTTPException, OSError) as exc:
        # Pas de marquage de notification : le prochain passage réessaiera.
        print(f"[PROGRESSION SALE] Impossible de notifier la fiche {key}: {exc}")


def sale_progress_is_fully_finished(message):
    """Une vraie clôture (bouton Terminer), pas « blanchiment terminé ».

    Les fiches « EN ATTENTE », « EN COURS » et « BLANCHIMENT TERMINÉ •
    RESTITUTION À CONFIRMER » restent suivies même après archivage de la feuille.
    """
    if sale_progress_is_manual_finished(message):
        return True
    status = sale_embed_field(message, "📌 Statut").upper()
    return ("TERMINÉ" in status or "TERMINE" in status) and "BLANCHIMENT TERMINÉ" not in status


def sale_progress_active_start(messages, week):
    """Début de la plus ancienne semaine portant un sale non clôturé.

    Les ventes terminées de cette même semaine restent dans la file FIFO :
    sinon leurs machines seraient réattribuées à une vente encore ouverte.
    """
    pending = [msg for msg in messages if not sale_progress_is_fully_finished(msg)]
    if not pending:
        return week
    earliest = min(sale_progress_week_key(msg.created_at) for msg in pending)
    return min(week, earliest)


async def sale_progress_reconcile():
    """Reconstruit chaque fois le total réel, y compris après reboot ou correction.

    Aucune écriture vers Google Sheets. Une seule tâche à la fois pour éviter
    les doubles notifications et les chevauchements d'édition Discord.
    """
    if not {"sales", "machines"} <= globals().get("_tenant_runtime_active_modules", {"sales", "machines"}):
        return
    # Évite de compter l'historique incomplet avant sa restauration au reboot.
    if not (_sale_progress_sale_history_ready.is_set()
            and _sale_progress_machine_history_ready.is_set()):
        return
    async with _sale_progress_lock:
        week = sale_progress_week_key()
        eligible = []
        history_start = datetime.now(timezone.utc) - timedelta(days=365)
        for channel_id in SALES_CHANNEL_IDS:
            channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            if not isinstance(channel, discord.abc.Messageable):
                raise ValueError("Le salon Discord configuré ne permet pas les messages.")
            async for msg in channel.history(after=history_start, limit=None, oldest_first=True):
                if bot.user is None or msg.author.id != bot.user.id or not msg.embeds:
                    continue
                row = sale_message_row(msg)
                if row is None or sale_progress_is_cancelled(msg):
                    continue
                amount = sale_progress_embed_amount(msg)
                if amount <= 0:
                    continue
                eligible.append((msg, row, amount))

        # Une fiche clôturée la semaine dernière ne doit PAS absorber les
        # nouvelles récupérations d'un sale qui attend encore d'être blanchi.
        open_items = [(msg, row, amount) for msg, row, amount in eligible
                      if not sale_progress_is_fully_finished(msg)]
        state = sale_progress_load_state(week)
        cohort = None
        if open_items:
            first_open_at = min(sale_progress_sale_start(msg) for msg, _, _ in open_items)
            first_open_message_at = min(msg.created_at for msg, _, _ in open_items)
        else:
            # Si la dernière fiche vient d'être clôturée, garder le même calcul.
            # Repartir de sa date seule risquerait de lui attribuer d'autres machines.
            cohort = state.get("cohort", {})
            first_open_at = sale_progress_datetime(cohort.get("first_open_at"))
            first_open_message_at = sale_progress_datetime(cohort.get("first_open_message_at"))
            if first_open_at is None or first_open_message_at is None:
                return
        active_from = min(week, sale_progress_week_key(first_open_at))
        machines, unknown = sale_progress_recovered_machines(
            load_reminders(), active_from, first_open_at=first_open_at
        )
        global _sale_progress_last_missing_date
        if unknown and _sale_progress_last_missing_date != (week, active_from):
            print(f"[PROGRESSION SALE] ATTENTION : {unknown} récupération(s) "
                  "à date incertaine : non comptées. Vérifier le statut et "
                  "les dates des anciennes machines si la progression est basse.")
            _sale_progress_last_missing_date = (week, active_from)

        sales = []
        messages = {}
        sale_records = load_sale_messages()
        for msg, row, amount in eligible:
            if cohort is not None and str(msg.id) not in cohort.get("message_ids", []):
                continue
            # Les ventes clôturées AVANT le plus ancien sale ouvert appartiennent
            # à l'historique, pas au pool de nouvelles machines récupérées.
            # Écarter les anciennes fiches clôturées avant les fiches ouvertes.
            # Utiliser ici l'heure de création Discord (pas la date JJ/MM du sale)
            # pour ne pas créditer une vente clôturée plus tôt le même dimanche.
            if msg.created_at < first_open_message_at and sale_progress_is_fully_finished(msg):
                continue
            sale = {
                "message_id": str(msg.id), "row": row,
                "created_at": sale_progress_sale_start(msg),
                "amount": amount, "group": sale_embed_field(msg, "🏴 Groupe", "Inconnu"),
                "progress_deduction": sale_records.get(str(msg.id), {}).get("progress_deduction", 0),
            }
            sales.append(sale)
            messages[str(msg.id)] = msg

        current_cohort = {
            "first_open_at": first_open_at.isoformat(),
            "first_open_message_at": first_open_message_at.isoformat(),
            "message_ids": sorted(messages),
        }
        if state.get("cohort") != current_cohort:
            state["cohort"] = current_cohort
            sale_progress_save_state(state)

        allocated, unallocated = sale_progress_allocate(sales, machines)
        # Journal synthétique seulement quand le total change, pour diagnostiquer
        # un 0 % sans spammer les logs à chaque vérification périodique.
        global _sale_progress_last_signature
        signature = (len(machines), sum(machines.values()), unknown,
                     tuple((s["message_id"], s["treated"], s["remaining"])
                           for s in allocated))
        if signature != _sale_progress_last_signature:
            print(f"[PROGRESSION SALE] {len(machines)} machine(s) RÉCUPÉRÉE(S), "
                  f"{format_money(sum(machines.values()))} comptabilisés ; "
                  f"{unknown} machine(s) historiques incertaines.")
            for sale in allocated:
                if not sale_progress_is_fully_finished(messages[sale["message_id"]]):
                    print(f"[PROGRESSION SALE] fiche={sale['message_id']} "
                          f"{format_money(sale['treated'])}/{format_money(sale['amount'])} "
                          f"({100 * sale['treated'] // sale['amount'] if sale['amount'] else 0} %)")
            _sale_progress_last_signature = signature
        allow_auto_notifications = unknown == 0
        for sale in allocated:
            msg = messages[sale["message_id"]]
            # Une clôture manuelle confirme la restitution, pas le pourcentage.
            # Les montants continuent à refléter les machines réellement récupérées.
            closed = sale_progress_is_fully_finished(msg)
            if closed and not any(field.name == SALE_PROGRESS_FIELD for field in msg.embeds[0].fields):
                # Les anciennes archives sans suivi chiffré restent telles quelles.
                continue
            emb, changed = sale_progress_update_embed(msg, sale["treated"], sale["amount"])
            if changed:
                try:
                    msg = await msg.edit(embed=emb)
                except (discord.Forbidden, discord.HTTPException) as exc:
                    print(f"[PROGRESSION SALE] Fiche {msg.id} non actualisée: {exc}")
                    continue
            if allow_auto_notifications and not closed:
                await sale_progress_announce(msg, sale, state, complete=(sale["remaining"] == 0))
        global _sale_progress_last_unallocated
        if unallocated and (week, active_from, unallocated) != _sale_progress_last_unallocated:
            print(f"[PROGRESSION SALE] {format_money(unallocated)} récupérés depuis "
                  f"{active_from} sans sale auquel les attribuer (aucune écriture Sheet).")
            _sale_progress_last_unallocated = (week, active_from, unallocated)


async def sale_progress_worker():
    await bot.wait_until_ready()
    # Attendre la vraie fin des deux migrations d'historique, pas un délai arbitraire.
    await _sale_progress_sale_history_ready.wait()
    await _sale_progress_machine_history_ready.wait()
    while not bot.is_closed():
        try:
            await sale_progress_reconcile()
        except Exception as exc:
            print(f"[PROGRESSION SALE] Synchronisation impossible : {exc}")
        await asyncio.sleep(SALE_PROGRESS_REFRESH_SECONDS)


def sale_progress_request_refresh():
    """Rafraîchissement rapide après clic sans bloquer la réponse Discord."""
    async def later():
        await asyncio.sleep(1)
        try:
            await sale_progress_reconcile()
        except Exception as exc:
            print(f"[PROGRESSION SALE] Mise à jour différée impossible : {exc}")
    asyncio.create_task(later())

# =========================
# BOT
# =========================
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

bot = globals().get("_tenant_bot_facade") or commands.Bot(command_prefix="!", intents=intents)
reminder_tasks: dict[str, asyncio.Task] = {}


async def sale_interaction_active(interaction, message=None):
    """Répond aux vieux boutons sans écrire dans Google Sheets."""
    target = message if message is not None else interaction.message
    if target is None:
        return True
    if sale_is_cancelled(target.id):
        await interaction.response.send_message(
            "❌ Ce sale a été annulé : la fiche est conservée pour l'historique.",
            ephemeral=True,
        )
        return False
    if not sale_is_expired(target):
        return True
    await interaction.response.send_message(
        "⏳ Cette fiche a plus de 365 jours : ses boutons ont expiré. "
        "Le message et les données du suivi sont conservés.",
        ephemeral=True,
    )
    row = sale_message_row(target)
    if row is not None:
        try:
            await target.edit(view=SaleStatusView(row, disabled=True))
        except (discord.Forbidden, discord.HTTPException):
            pass
    return False


class FinishSaleModal(discord.ui.Modal, title="Terminer le sale"):
    returned_date = discord.ui.TextInput(
        label="Date rendu",
        placeholder="Vide = aujourd'hui, sinon JJ/MM ou JJ/MM/AAAA",
        required=False,
        max_length=10,
    )

    def __init__(self, sheet_row: int, original_message: discord.Message, receiver: str):
        super().__init__()
        self.sheet_row = sheet_row
        self.original_message = original_message
        self.receiver = receiver

    async def on_submit(self, interaction: discord.Interaction):
        if not await sale_interaction_active(interaction, self.original_message):
            return
        raw_date = self.returned_date.value.strip()
        if raw_date:
            try:
                returned_date = parse_sale_date(raw_date)
            except ValueError as exc:
                await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
                return
        else:
            returned_date = datetime.now(TIMEZONE).strftime("%d/%m/%Y")

        await interaction.response.defer(ephemeral=True)

        try:
            async with _sale_progress_lock:
                # Le formulaire peut être resté ouvert pendant une récupération.
                # Relire sous le même verrou que le calcul évite de rétablir un ancien %.
                current = await self.original_message.channel.fetch_message(self.original_message.id)
                if sale_is_cancelled(current.id) or sale_is_expired(current):
                    raise ValueError("Cette fiche a été annulée ou a expiré.")
                if sale_progress_is_fully_finished(current):
                    raise ValueError("Ce sale a déjà été clôturé. Rouvre la fiche pour vérifier son état.")
                if self.receiver not in SALE_EMPLOYEES:
                    raise ValueError("Cette personne a été supprimée. Rouvre le menu.")
                worksheet_name = await resolve_sale_worksheet(current, self.sheet_row)
                receiver_id = SALE_EMPLOYEES[self.receiver]
                await run_blocking(
                    finish_sale_sheet, self.sheet_row, receiver_id, returned_date, worksheet_name
                )
                embed = current.embeds[0].copy() if current.embeds else discord.Embed()
                upsert_sale_embed_field(embed, "📌 Statut", "🟢 **TERMINÉ**", inline=False)
                upsert_sale_embed_field(embed, "📦 Joueur qui récupère", receiver_id, inline=True)
                upsert_sale_embed_field(embed, "📅 Date rendu", returned_date, inline=True)
                await current.edit(embed=embed, view=SaleStatusView(self.sheet_row))
                print(
                    f"[SALE] Clôture fiche={current.id} ligne={self.sheet_row} "
                    f"auteur={interaction.user.id} destinataire={receiver_id} "
                    f"date_rendu={returned_date} heure={datetime.now(TIMEZONE).isoformat()}",
                    flush=True,
                )
            sale_progress_request_refresh()
            # Ferme automatiquement "Qui récupère le sale ?" après validation.
            try:
                await interaction.delete_original_response()
            except (discord.NotFound, discord.HTTPException):
                pass
        except Exception as exc:
            await interaction.followup.send(
                f"❌ Impossible de terminer le sale : `{exc}`",
                ephemeral=True
            )


class ReceiverSelect(discord.ui.Select):
    def __init__(self, sheet_row: int, original_message: discord.Message):
        self.sheet_row = sheet_row
        self.original_message = original_message
        options = [
            discord.SelectOption(label=name, value=name, description=f"ID : {unique_id}")
            for name, unique_id in SALE_EMPLOYEES.items()
        ]
        super().__init__(
            placeholder="Choisir le joueur qui récupère",
            min_values=1,
            max_values=1,
            options=options or [discord.SelectOption(label="Aucune personne disponible", value="empty")],
            disabled=not options,
            custom_id=f"receiver_select:{sheet_row}",
        )

    async def callback(self, interaction: discord.Interaction):
        if not await sale_interaction_active(interaction, self.original_message):
            return
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, SALE_STATUS_ROLES):
            await interaction.response.send_message(
                "❌ Tu n'as pas l'autorisation de terminer ce sale.",
                ephemeral=True
            )
            return

        receiver = self.values[0]
        if receiver not in SALE_EMPLOYEES:
            await interaction.response.send_message("⚠️ Cette personne a été supprimée. Rouvre le menu.", ephemeral=True)
            return
        await interaction.response.send_modal(
            FinishSaleModal(
                self.sheet_row,
                self.original_message,
                receiver
            )
        )

class ReceiverSelectView(discord.ui.View):
    def __init__(self, sheet_row: int, original_message: discord.Message):
        super().__init__(timeout=120)
        self.add_item(ReceiverSelect(sheet_row, original_message))


class EditSaleModal(discord.ui.Modal, title="Modifier le sale"):
    """Cinq champs maximum, préremplis à partir de la fiche Discord."""
    def __init__(self, sheet_row: int, original_message: discord.Message):
        super().__init__(timeout=300)
        self.sheet_row = sheet_row
        self.original_message = original_message
        self.previous_employee = sale_embed_field(original_message, "👤 Employé")
        self.previous_giver = re.sub(
            r"\D", "", sale_embed_field(
                original_message, "🪪 Joueur qui donne",
                sale_embed_field(original_message, "👤 Qui / ID")
            )
        )
        self.employee = discord.ui.TextInput(
            label="Employé (nom ou ID)",
            placeholder="Tom Kerrigan, Donatello, Lily, Ekio",
            default=self.previous_employee,
            max_length=100,
        )
        self.group = discord.ui.TextInput(
            label="Groupe",
            placeholder=" / ".join(SALE_GROUPS)[:100],
            default=sale_embed_field(original_message, "🏴 Groupe"),
            max_length=100,
        )
        self.giver = discord.ui.TextInput(
            label="ID du joueur qui donne",
            default=self.previous_giver,
            max_length=20,
        )
        self.received_date = discord.ui.TextInput(
            label="Date reçue",
            placeholder="JJ/MM ou JJ/MM/AAAA",
            default=sale_embed_field(
                original_message, "📅 Date reçu",
                sale_embed_field(original_message, "📅 Date")
            ),
            max_length=10,
        )
        self.amount = discord.ui.TextInput(
            label="Somme à blanchir",
            default=re.sub(r"\D", "", sale_embed_field(original_message, "💰 Somme à blanchir")),
            max_length=20,
        )
        for item in (self.employee, self.group, self.giver, self.received_date, self.amount):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        if not await sale_interaction_active(interaction, self.original_message):
            return
        if not sale_can_correct(interaction.user, self.original_message.id):
            await interaction.response.send_message(
                "❌ Seul l'auteur du sale ou un responsable peut le modifier.", ephemeral=True
            )
            return
        try:
            employee = normalize_sale_employee(self.employee.value)
            group = normalize_sale_group(self.group.value)
            date_text = parse_sale_date(self.received_date.value)
            raw_amount = re.sub(r"[\s.,]", "", self.amount.value.strip())
            if not raw_amount.isdigit() or int(raw_amount) <= 0:
                raise ValueError("La somme doit être un nombre supérieur à zéro.")
            amount = int(raw_amount)
            giver_id = self.giver.value.strip()
            if not giver_id.isdigit() or int(giver_id) <= 0:
                raise ValueError("L'ID du joueur qui donne doit être un nombre valide.")
            # Si l'employé change et que l'ancien ID est resté inchangé,
            # on adapte automatiquement l'ID au nouvel employé.
            if (employee != self.previous_employee and giver_id == self.previous_giver):
                giver_id = SALE_EMPLOYEES[employee]
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            worksheet_name = await resolve_sale_worksheet(self.original_message, self.sheet_row)
            await run_blocking(edit_sale_sheet, self.sheet_row, date_text, group,
                               employee, giver_id, amount, worksheet_name)
            embed = (self.original_message.embeds[0].copy()
                     if self.original_message.embeds else discord.Embed())
            upsert_sale_embed_field(embed, "👤 Employé", employee)
            upsert_sale_embed_field(embed, "🪪 Joueur qui donne", giver_id)
            upsert_sale_embed_field(embed, "🏴 Groupe", group)
            upsert_sale_embed_field(embed, "💰 Somme à blanchir", f"**{format_money(amount)}**")
            upsert_sale_embed_field(embed, "📅 Date reçu", date_text)
            updated_message = await self.original_message.edit(
                embed=embed, view=SaleStatusView(self.sheet_row)
            )
            # discord.py renvoie le NOUVEAU Message : l'ancien objet peut
            # conserver les champs précédents. Enregistrer la nouvelle empreinte.
            register_sale_message(updated_message, self.sheet_row, worksheet_name)
            sale_progress_request_refresh()
            await interaction.followup.send(
                "✅ Sale corrigé sur Discord et dans le suivi.", ephemeral=True
            )
            try:
                await interaction.delete_original_response()
            except (discord.NotFound, discord.HTTPException):
                pass
        except Exception as exc:
            await interaction.followup.send(
                f"❌ Modification impossible : `{exc}`. "
                "Si les données du suivi ont déjà été modifiées, vérifie la fiche avant de réessayer.",
                ephemeral=True,
            )


class CancelSaleConfirmView(discord.ui.View):
    """La confirmation est privée ; aucun message public Discord n'est supprimé."""
    def __init__(self, sheet_row: int, original_message: discord.Message, requester_id: int):
        super().__init__(timeout=120)
        self.sheet_row = sheet_row
        self.original_message = original_message
        self.requester_id = requester_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "❌ Cette confirmation ne t'appartient pas.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Oui, annuler ce sale", emoji="❌",
                       style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await sale_interaction_active(interaction, self.original_message):
            return
        if not sale_can_correct(interaction.user, self.original_message.id):
            await interaction.response.send_message(
                "❌ Seul l'auteur du sale ou un responsable peut l'annuler.", ephemeral=True
            )
            return
        # La réponse différée met à jour UNIQUEMENT la confirmation privée.
        await interaction.response.defer()
        try:
            worksheet_name = await resolve_sale_worksheet(self.original_message, self.sheet_row)
            # Sauvegarder d'abord l'association pour les anciennes fiches.
            register_sale_message(self.original_message, self.sheet_row, worksheet_name)
            await run_blocking(cancel_sale_sheet, self.sheet_row, worksheet_name)
            mark_sale_cancelled(self.original_message.id, interaction.user.id)
            sale_progress_request_refresh()
            embed = (self.original_message.embeds[0].copy()
                     if self.original_message.embeds else discord.Embed())
            upsert_sale_embed_field(embed, "📌 Statut", "❌ **ANNULÉ**", inline=False)
            upsert_sale_embed_field(embed, "🗑️ Annulé par", interaction.user.display_name,
                                    inline=False)
            await self.original_message.edit(
                embed=embed, view=SaleStatusView(self.sheet_row, disabled=True)
            )
            await interaction.edit_original_response(
                content="✅ Sale annulé. Les données de cette opération ont été effacées dans le suivi. "
                        "La fiche Discord reste visible.",
                view=None,
            )
        except Exception as exc:
            await interaction.followup.send(
                f"❌ Annulation impossible : `{exc}`. "
                "Si la ligne a déjà été vidée, ne relance pas l'opération ; vérifie la fiche.",
                ephemeral=True,
            )

    @discord.ui.button(label="Non, conserver", emoji="↩️",
                       style=discord.ButtonStyle.secondary)
    async def abort(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="↩️ Annulation abandonnée. Le sale n'a pas été modifié.", view=None
        )


class SaleStatusView(discord.ui.View):
    def __init__(self, sheet_row: int, disabled: bool = False):
        super().__init__(timeout=None)
        self.sheet_row = sheet_row

        waiting = discord.ui.Button(
            label="En attente",
            emoji="🟡",
            style=discord.ButtonStyle.secondary,
            custom_id=f"sale_waiting:{sheet_row}",
        )
        progress = discord.ui.Button(
            label="En cours",
            emoji="🔵",
            style=discord.ButtonStyle.primary,
            custom_id=f"sale_progress:{sheet_row}",
        )
        finished = discord.ui.Button(
            label="Terminé",
            emoji="🟢",
            style=discord.ButtonStyle.success,
            custom_id=f"sale_finished:{sheet_row}",
        )
        add_new = discord.ui.Button(
            label="Ajouter du sale",
            emoji="➕",
            style=discord.ButtonStyle.secondary,
            custom_id=f"sale_add_new:{sheet_row}",
        )
        waiting.callback = self.set_waiting
        progress.callback = self.set_progress
        finished.callback = self.set_finished
        edit = discord.ui.Button(
            label="Modifier",
            emoji="✏️",
            style=discord.ButtonStyle.secondary,
            custom_id=f"sale_edit:{sheet_row}",
            row=1,
        )
        cancel = discord.ui.Button(
            label="Annuler",
            emoji="❌",
            style=discord.ButtonStyle.danger,
            custom_id=f"sale_cancel:{sheet_row}",
            row=1,
        )
        add_new.callback = self.add_new_sale
        edit.callback = self.edit_sale
        cancel.callback = self.cancel_sale
        self.add_item(waiting)
        self.add_item(progress)
        self.add_item(finished)
        self.add_item(add_new)
        self.add_item(edit)
        self.add_item(cancel)
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = disabled

    async def edit_sale(self, interaction: discord.Interaction):
        if interaction.message is None:
            await interaction.response.send_message("❌ Fiche Discord introuvable.", ephemeral=True)
            return
        if not await sale_interaction_active(interaction):
            return
        if not sale_can_correct(interaction.user, interaction.message.id):
            await interaction.response.send_message(
                "❌ Seul l'auteur du sale ou un responsable peut le modifier.", ephemeral=True
            )
            return
        await interaction.response.send_modal(EditSaleModal(self.sheet_row, interaction.message))

    async def cancel_sale(self, interaction: discord.Interaction):
        if interaction.message is None:
            await interaction.response.send_message("❌ Fiche Discord introuvable.", ephemeral=True)
            return
        if not await sale_interaction_active(interaction):
            return
        if not sale_can_correct(interaction.user, interaction.message.id):
            await interaction.response.send_message(
                "❌ Seul l'auteur du sale ou un responsable peut l'annuler.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "⚠️ **Confirmer l'annulation ?**\n"
            "Toutes les données de ce sale seront effacées du suivi. "
            "La fiche Discord restera visible, mais ne pourra plus être modifiée.",
            view=CancelSaleConfirmView(self.sheet_row, interaction.message, interaction.user.id),
            ephemeral=True,
        )

    async def change_status(self, interaction: discord.Interaction, status: str, icon: str):
        if interaction.message is None:
            await interaction.response.send_message("❌ Fiche Discord introuvable.", ephemeral=True)
            return
        if not await sale_interaction_active(interaction):
            return
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, SALE_STATUS_ROLES):
            await interaction.response.send_message(
                "❌ Tu n'as pas l'autorisation de modifier ce statut.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            worksheet_name = await resolve_sale_worksheet(interaction.message, self.sheet_row)
            await run_blocking(update_sale_status_sheet, self.sheet_row, status, worksheet_name)

            embed = interaction.message.embeds[0].copy() if interaction.message.embeds else discord.Embed()
            found = False
            for index, field in enumerate(embed.fields):
                if field.name == "📌 Statut":
                    embed.set_field_at(index, name="📌 Statut", value=f"{icon} **{status.upper()}**", inline=False)
                    found = True
                    break
            if not found:
                embed.add_field(name="📌 Statut", value=f"{icon} **{status.upper()}**", inline=False)

            await interaction.message.edit(embed=embed, view=self)
        except Exception as exc:
            await interaction.followup.send(
                f"❌ Impossible de mettre à jour le statut : `{exc}`",
                ephemeral=True
            )

    async def add_new_sale(self, interaction: discord.Interaction):
        if not await sale_interaction_active(interaction):
            return
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, SALE_ADD_ROLES):
            await interaction.response.send_message(
                "❌ Tu n'as pas l'autorisation d'ajouter du sale.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "👤 **Choisis l'employé :**",
            view=EmployeeSelectView(),
            ephemeral=True
        )

    async def set_waiting(self, interaction: discord.Interaction):
        await self.change_status(interaction, "en attente", "🟡")

    async def set_progress(self, interaction: discord.Interaction):
        if interaction.message is None:
            await interaction.response.send_message("❌ Fiche Discord introuvable.", ephemeral=True)
            return
        if not await sale_interaction_active(interaction):
            return
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, SALE_STATUS_ROLES):
            await interaction.response.send_message(
                "❌ Tu n'as pas l'autorisation de modifier ce statut.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            # Le menu Google Sheets ne contient que "en attente" et "Terminé".
            # On laisse donc la valeur valide "en attente" dans le Sheet.
            worksheet_name = await resolve_sale_worksheet(interaction.message, self.sheet_row)
            await run_blocking(update_sale_status_sheet, self.sheet_row, "en attente", worksheet_name)

            embed = interaction.message.embeds[0].copy() if interaction.message.embeds else discord.Embed()
            found = False
            for index, field in enumerate(embed.fields):
                if field.name == "📌 Statut":
                    embed.set_field_at(index, name="📌 Statut", value="🔵 **EN COURS**", inline=False)
                    found = True
                    break
            if not found:
                embed.add_field(name="📌 Statut", value="🔵 **EN COURS**", inline=False)

            await interaction.message.edit(embed=embed, view=self)
        except Exception as exc:
            await interaction.followup.send(
                f"❌ Impossible de mettre à jour le statut : `{exc}`",
                ephemeral=True
            )

    async def set_finished(self, interaction: discord.Interaction):
        if interaction.message is None:
            await interaction.response.send_message("❌ Fiche Discord introuvable.", ephemeral=True)
            return
        if not await sale_interaction_active(interaction):
            return
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, SALE_STATUS_ROLES):
            await interaction.response.send_message(
                "❌ Tu n'as pas l'autorisation de terminer ce sale.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "📦 **Qui récupère le sale ?**",
            view=ReceiverSelectView(self.sheet_row, interaction.message),
            ephemeral=True
        )


class LegacySaleResetView(discord.ui.View):
    """Intercepte le bouton Reset des anciennes fiches en attendant leur mise à jour."""
    def __init__(self, row: int):
        super().__init__(timeout=None)
        button = discord.ui.Button(
            label="Reset semaine",
            emoji="🔄",
            style=discord.ButtonStyle.danger,
            custom_id=f"sale_reset_week:{row}",
        )
        button.callback = self.redirect
        self.add_item(button)

    async def redirect(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "ℹ️ Le Reset semaine se fait uniquement depuis le panneau Gestion du sale.",
            ephemeral=True,
        )


class SaleAmountModal(discord.ui.Modal, title="Informations du sale"):
    received_date = discord.ui.TextInput(
        label="Date reçu",
        placeholder="Vide = aujourd'hui, sinon JJ/MM ou JJ/MM/AAAA",
        required=False,
        max_length=10,
    )

    amount = discord.ui.TextInput(
        label="Somme à blanchir",
        placeholder="Vide = 5 000 000 $",
        required=False,
        max_length=20,
    )

    def __init__(self, employee: str, giver_id: str, group: str):
        super().__init__()
        self.employee = employee
        self.giver_id = giver_id
        self.group = group

    async def on_submit(self, interaction: discord.Interaction):
        raw_date = self.received_date.value.strip()
        if raw_date:
            try:
                date_text = parse_sale_date(raw_date)
            except ValueError as exc:
                await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
                return
        else:
            date_text = datetime.now(TIMEZONE).strftime("%d/%m/%Y")

        raw_amount = self.amount.value.strip().replace(" ", "").replace(".", "").replace(",", "")
        if not raw_amount:
            amount = 5_000_000
        elif raw_amount.isdigit() and int(raw_amount) > 0:
            amount = int(raw_amount)
        else:
            await interaction.response.send_message(
                "❌ La somme doit être un nombre supérieur à 0.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            row = await run_blocking(
                add_sale_to_sheet,
                date_text,
                self.group,
                self.employee,
                self.giver_id,
                amount,
            )

            embed = discord.Embed(title=f"📋 SALE • Ligne {row}")
            embed.add_field(name="👤 Employé", value=self.employee, inline=True)
            embed.add_field(name="🪪 Joueur qui donne", value=self.giver_id, inline=True)
            embed.add_field(name="🏴 Groupe", value=self.group, inline=True)
            embed.add_field(name="💰 Somme à blanchir", value=f"**{format_money(amount)}**", inline=True)
            embed.add_field(name="📅 Date reçu", value=date_text, inline=True)
            embed.add_field(name="📌 Statut", value="🟡 **EN ATTENTE**", inline=False)

            channel = interaction.channel
            if not isinstance(channel, discord.abc.Messageable):
                raise ValueError("Le salon ne permet pas les messages.")
            message = await channel.send(
                embed=embed,
                view=SaleStatusView(row)
            )
            try:
                register_sale_message(message, row, SALES_WORKSHEET,
                                      creator_id=interaction.user.id)
                sale_progress_request_refresh()
            except Exception as exc:
                # Le sale est déjà créé; ne pas signaler un faux échec à l'employé.
                print(f"[SALE] Fiche {message.id} créée, sauvegarde du lien impossible : {exc}")
            # Ferme automatiquement le message privé temporaire une fois enregistré.
            try:
                await interaction.delete_original_response()
            except (discord.NotFound, discord.HTTPException):
                pass
        except Exception as exc:
            await interaction.followup.send(
                f"❌ Impossible d'ajouter du sale : `{exc}`",
                ephemeral=True
            )

class GroupSelect(discord.ui.Select):
    def __init__(self, employee: str, giver_id: str):
        self.employee = employee
        self.giver_id = giver_id
        options = [discord.SelectOption(label=group, value=group) for group in SALE_GROUPS]
        super().__init__(
            placeholder="Choisir le groupe",
            min_values=1,
            max_values=1,
            options=options or [discord.SelectOption(label="Aucun groupe disponible", value="empty")],
            disabled=not options,
            custom_id="sale_group_select",
        )

    async def callback(self, interaction: discord.Interaction):
        if self.employee not in SALE_EMPLOYEES or self.values[0] not in SALE_GROUPS:
            await interaction.response.send_message("⚠️ Cette personne ou ce groupe a été supprimé. Rouvre le menu.", ephemeral=True)
            return
        await interaction.response.send_modal(
            SaleAmountModal(self.employee, self.giver_id, self.values[0])
        )


class GroupSelectView(discord.ui.View):
    def __init__(self, employee: str, giver_id: str):
        super().__init__(timeout=120)
        self.add_item(GroupSelect(employee, giver_id))


class EmployeeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=name, value=name, description=f"ID : {unique_id}")
            for name, unique_id in SALE_EMPLOYEES.items()
        ]
        super().__init__(
            placeholder="Choisir l'employé",
            min_values=1,
            max_values=1,
            options=options or [discord.SelectOption(label="Aucune personne disponible", value="empty")],
            disabled=not options,
            custom_id="sale_employee_select",
        )

    async def callback(self, interaction: discord.Interaction):
        employee = self.values[0]
        if employee not in SALE_EMPLOYEES:
            await interaction.response.send_message("⚠️ Cette personne a été supprimée. Rouvre le menu.", ephemeral=True)
            return
        giver_id = SALE_EMPLOYEES[employee]
        await interaction.response.edit_message(
            content=f"👤 Employé : **{employee}** • ID : **{giver_id}**\n🏴 Choisis maintenant le groupe :",
            view=GroupSelectView(employee, giver_id)
        )


class EmployeeSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(EmployeeSelect())


class SaleChoiceModal(discord.ui.Modal):
    def __init__(self, employee: bool):
        super().__init__(title="Ajouter une personne" if employee else "Ajouter un groupe")
        self.employee = employee
        self.name_input = discord.ui.TextInput(
            label="Nom de la personne" if employee else "Nom du groupe",
            max_length=70 if employee else 100,
        )
        self.add_item(self.name_input)
        if employee:
            self.id_input = discord.ui.TextInput(label="ID du joueur", max_length=20)
            self.add_item(self.id_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, SALE_STATUS_ROLES):
            await interaction.response.send_message("❌ Tu n'as pas l'autorisation de gérer les personnes et groupes.", ephemeral=True)
            return
        name = str(self.name_input.value).strip()
        employees = dict(SALE_EMPLOYEES)
        groups = list(SALE_GROUPS)
        error = None
        if not name:
            error = "Le nom est obligatoire."
        elif self.employee:
            uid = str(self.id_input.value).strip()
            if not uid.isascii() or not uid.isdigit():
                error = "L'ID du joueur doit contenir uniquement des chiffres."
            elif any(uid == existing_id or name.casefold() in {label.casefold(), label.rsplit(' ', 1)[0].casefold()}
                     for label, existing_id in employees.items()):
                error = "Cette personne ou cet ID existe déjà."
            elif len(employees) >= 25:
                error = "Le menu Discord est limité à 25 personnes."
            else:
                employees[f"{name} {uid}"] = uid
        elif name.casefold() in {group.casefold() for group in groups}:
            error = "Ce groupe existe déjà."
        elif len(groups) >= 25:
            error = "Le menu Discord est limité à 25 groupes."
        else:
            groups.append(name)
        if error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        try:
            save_sale_choices(employees, groups)
        except OSError:
            await interaction.response.send_message("❌ Sauvegarde impossible. Aucun ajout effectué.", ephemeral=True)
            return
        SALE_EMPLOYEES.update(employees)
        SALE_GROUPS[:] = groups
        await interaction.response.send_message(
            f"✅ **{name}** ajouté{'e' if self.employee else ''}. Disponible dans les prochains menus.",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
        )


class SaleChoiceDeleteSelect(discord.ui.Select):
    def __init__(self, employee: bool):
        self.employee = employee
        names = list(SALE_EMPLOYEES) if employee else list(SALE_GROUPS)
        super().__init__(
            placeholder="Choisir la personne à supprimer" if employee else "Choisir le groupe à supprimer",
            options=[discord.SelectOption(label=name, value=name) for name in names],
        )

    async def callback(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, SALE_STATUS_ROLES):
            await interaction.response.send_message("❌ Tu n'as pas l'autorisation de gérer les personnes et groupes.", ephemeral=True)
            return
        name = self.values[0]
        employees = dict(SALE_EMPLOYEES)
        groups = list(SALE_GROUPS)
        if name not in (employees if self.employee else groups):
            await interaction.response.edit_message(content="ℹ️ Cet élément a déjà été supprimé.", view=None)
            return
        if self.employee:
            del employees[name]
        else:
            groups.remove(name)
        try:
            save_sale_choices(employees, groups)
        except OSError:
            await interaction.response.send_message("❌ Sauvegarde impossible. Aucune suppression effectuée.", ephemeral=True)
            return
        SALE_EMPLOYEES.clear()
        SALE_EMPLOYEES.update(employees)
        SALE_GROUPS[:] = groups
        await interaction.response.edit_message(
            content=f"✅ **{name}** supprimé des choix. Les anciennes fiches sont conservées.",
            view=None, allowed_mentions=discord.AllowedMentions.none(),
        )


class SalesPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def open_delete_menu(self, interaction: discord.Interaction, employee: bool):
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, SALE_STATUS_ROLES):
            await interaction.response.send_message("❌ Tu n'as pas l'autorisation de gérer les personnes et groupes.", ephemeral=True)
            return
        if not (SALE_EMPLOYEES if employee else SALE_GROUPS):
            await interaction.response.send_message("ℹ️ La liste est déjà vide.", ephemeral=True)
            return
        view = discord.ui.View(timeout=120)
        view.add_item(SaleChoiceDeleteSelect(employee))
        await interaction.response.send_message(
            "Sélectionne l'élément à supprimer des prochains menus. Les anciennes fiches sont conservées.",
            view=view, ephemeral=True,
        )

    @discord.ui.button(label="Supprimer une personne", style=discord.ButtonStyle.danger,
                       custom_id="panel:delete_employee", row=1)
    async def delete_employee(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.open_delete_menu(interaction, True)

    @discord.ui.button(label="Supprimer un groupe", style=discord.ButtonStyle.danger,
                       custom_id="panel:delete_group", row=1)
    async def delete_group(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.open_delete_menu(interaction, False)

    async def open_choice_modal(self, interaction: discord.Interaction, employee: bool):
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, SALE_STATUS_ROLES):
            await interaction.response.send_message("❌ Tu n'as pas l'autorisation de gérer les personnes et groupes.", ephemeral=True)
            return
        await interaction.response.send_modal(SaleChoiceModal(employee))

    @discord.ui.button(label="Ajouter une personne", emoji="👤", style=discord.ButtonStyle.secondary,
                       custom_id="panel:add_employee")
    async def add_employee(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.open_choice_modal(interaction, True)

    @discord.ui.button(label="Ajouter un groupe", emoji="🏴", style=discord.ButtonStyle.secondary,
                       custom_id="panel:add_group")
    async def add_group(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.open_choice_modal(interaction, False)

    @discord.ui.button(
        label="Reset semaine",
        emoji="🔄",
        style=discord.ButtonStyle.danger,
        custom_id="panel:reset_week",
    )
    async def reset_week(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, SALE_STATUS_ROLES):
            await interaction.response.send_message(
                "❌ Tu n'as pas l'autorisation de reset la semaine.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            archive_name = await run_blocking(reset_sales_week_sheet)
            today = datetime.now(TIMEZONE).date().isoformat()
            save_weekly_reset_state(today, archive_name)
            await interaction.followup.send(
                f"✅ Reset effectué : **En cours → {archive_name}** puis **Modele → En cours**.",
                ephemeral=True
            )
        except Exception as exc:
            await interaction.followup.send(
                f"❌ Impossible de reset la semaine : `{exc}`",
                ephemeral=True
            )

    @discord.ui.button(
        label="Ajouter du sale",
        emoji="➕",
        style=discord.ButtonStyle.primary,
        custom_id="panel:add_sale",
    )
    async def add_sale(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, SALE_ADD_ROLES):
            await interaction.response.send_message(
                "❌ Tu n'as pas l'autorisation d'ajouter du sale.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "👤 **Choisis l'employé :**",
            view=EmployeeSelectView(),
            ephemeral=True
        )


class MachineModal(discord.ui.Modal, title="Lancer une machine"):
    amount = discord.ui.TextInput(
        label="Montant",
        placeholder="Vide = 1 000 000 $ • Maximum 1 000 000 $",
        required=False,
        max_length=20,
    )

    async def on_submit(self, interaction: discord.Interaction):
        # IMPORTANT : thinking=True force une vraie réponse éphémère séparée.
        # Sans ça, un Modal ouvert depuis un bouton public peut utiliser
        # deferred_message_update et edit_original_response() peut alors viser
        # le message public qui a ouvert le Modal.
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ Cette action doit être utilisée sur le serveur.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)

        raw = self.amount.value.strip().replace(" ", "").replace(".", "").replace(",", "")
        if not raw:
            amount = DEFAULT_MACHINE_AMOUNT
        else:
            if not raw.isdigit():
                await interaction.followup.send("❌ Le montant doit contenir uniquement des chiffres.", ephemeral=True)
                return
            amount = int(raw)

        if amount <= 0:
            await interaction.followup.send("❌ Le montant doit être supérieur à 0 $.", ephemeral=True)
            return
        if amount > MAX_MACHINE_AMOUNT:
            await interaction.followup.send("❌ Une machine ne peut pas dépasser **1 000 000 $**.", ephemeral=True)
            return

        now = datetime.now(TIMEZONE)
        finish = machine_time_shift(now, MACHINE_DURATION)

        try:
            row = await run_blocking(
                add_machine_to_sheet,
                now.strftime("%d/%m/%Y"),
                now.strftime("%H:%M"),
                amount,
                display_name(interaction.user),
            )

            embed = discord.Embed(title="⚙️ MACHINE LANCÉE")
            embed.add_field(name="👤 Lancée par", value=interaction.user.mention, inline=False)
            embed.add_field(name="💰 Montant", value=f"**{format_money(amount)}**", inline=True)
            embed.add_field(name="🕐 Lancement", value=machine_display_time(now), inline=False)
            embed.add_field(name="🏁 Fin prévue", value=machine_display_time(finish), inline=False)

            target = bot.get_channel(MACHINE_REMINDER_CHANNEL_ID)
            if target is None:
                target = await bot.fetch_channel(MACHINE_REMINDER_CHANNEL_ID)
            if not isinstance(target, discord.abc.Messageable):
                raise ValueError("Le salon Discord configuré ne permet pas les messages.")

            role = machine_reminder_role(interaction.guild)
            if role is None:
                await interaction.followup.send(
                    "❌ Rôle **Employés** introuvable sur le serveur.",
                    ephemeral=True
                )
                return

            # Use a stable id before sending so the card buttons and reminder share it.
            launch_id = f"machine-{int(datetime.now(TIMEZONE).timestamp() * 1000)}"

            msg = await target.send(
                content=f"🔔 {role.mention} **Une machine vient d'être lancée !**",
                embed=embed,
                view=MachineLaunchView(launch_id, row),
                allowed_mentions=discord.AllowedMentions(roles=True)
            )
            print(
                f"[MACHINES] Nouvelle carte créée : message={msg.id} "
                f"machine={launch_id} | aucun ancien message supprimé."
            )

            reminder = {
                "id": launch_id,
                "message_id": str(msg.id),
                "channel_id": MACHINE_REMINDER_CHANNEL_ID,
                "user_id": interaction.user.id,
                "amount": amount,
                "launched_at": now.isoformat(),
                "finish_at": finish.isoformat(),
                "sheet_row": row,
                "recovered": False,
                "finished_notified": False,
                "message_ids": [str(msg.id)],
            }
            # Nouvelle machine réellement lancée :
            # IMPORTANT : on ne supprime PLUS aucun ancien suivi de machine ici.
            # Les anciennes machines, récupérées ou non, restent enregistrées
            # afin que leurs messages et boutons persistent après les redémarrages.
            reminders = load_reminders()
            reminders.append(reminder)
            save_reminders(reminders)

            await increment_machine_stat(interaction.user)
            schedule_reminder(reminder)

            await send_machine_log(
                f"✅ **Machine enregistrée par {interaction.user.display_name}**\n"
                f"📋 Référence dans le suivi : **{row}**\n"
                f"💰 Montant : **{amount:,.0f} $**\n"
                f"⏰ Rappel prévu : **{finish.strftime('%H:%M')}**"
            )
            
            # Confirme le lancement dans la réponse privée du formulaire.
            # On ne supprime aucune réponse dans le flux de lancement, ce qui
            # évite toute ambiguïté avec un ancien message Discord.
            try:
                await interaction.edit_original_response(
                    content=f"✅ Machine lancée. Fin prévue à **{finish.strftime('%H:%M')}**."
                )
            except (discord.NotFound, discord.HTTPException):
                pass

        except Exception as exc:
            await interaction.followup.send(f"❌ Impossible de lancer la machine : `{exc}`", ephemeral=True)


async def send_machine_log(message: str):
    if not MACHINE_LOGS_CHANNEL_ID:
        return
    channel = bot.get_channel(MACHINE_LOGS_CHANNEL_ID)
    if channel is None:
        channel = await bot.fetch_channel(MACHINE_LOGS_CHANNEL_ID)
    if not isinstance(channel, discord.abc.Messageable):
        raise ValueError("Le salon Discord configuré ne permet pas les messages.")
    await channel.send(message)


def machine_reminder_role(guild):
    role_id = globals().get("MACHINE_REMINDER_ROLE_ID")
    if role_id:
        return guild.get_role(int(role_id))
    return discord.utils.get(guild.roles, name=MACHINE_REMINDER_ROLE_NAME)


def load_machine_stats():
    default = {"week_start": None, "message_id": None, "users": {}, "history": {}}
    if not MACHINE_STATS_FILE.exists():
        return default
    try:
        data = json.loads(MACHINE_STATS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Format de statistiques invalide")
        for key, value in default.items():
            data.setdefault(key, value)
        if not isinstance(data.get("users"), dict):
            data["users"] = {}
        if not isinstance(data.get("history"), dict):
            data["history"] = {}
        return data
    except Exception as exc:
        print(f"[MACHINES] Lecture des statistiques impossible : {exc}")
        return default


def save_machine_stats(data):
    """Écriture atomique : ne pas perdre les classements archivés sur un crash."""
    tmp = MACHINE_STATS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(MACHINE_STATS_FILE)


def current_week_start():
    now = datetime.now(TIMEZONE)
    monday = now.date() - timedelta(days=now.weekday())
    return monday.isoformat()


def start_new_machine_stats_report(data, new_week, *, force=False):
    """Fige les statistiques précédentes et prépare un NOUVEAU message Discord.

    Conserve aussi une copie locale dans machine_weekly_stats.json -> history.
    Retourne (nouvelles_stats, ancien_rapport_à_finaliser).
    """
    previous_week = data.get("week_start")
    if previous_week == new_week and not force:
        return data, None

    previous_report = None
    if previous_week and (data.get("message_id") or data.get("users")):
        previous_report = {
            "week_start": previous_week,
            "message_id": data.get("message_id"),
            "users": json.loads(json.dumps(data.get("users", {}), ensure_ascii=False)),
        }
        history = data.setdefault("history", {})
        key = previous_week
        if key in history:
            # Cas d'un reset manuel en cours de semaine : ne pas écraser
            # l'archive du classement précédent.
            suffix = 2
            while f"{previous_week} ({suffix})" in history:
                suffix += 1
            key = f"{previous_week} ({suffix})"
        history[key] = {
            **previous_report,
            "archived_at": datetime.now(TIMEZONE).isoformat(),
        }

    data["week_start"] = new_week
    data["message_id"] = None  # Force channel.send() au lieu d'éditer l'ancien.
    data["users"] = {}
    return data, previous_report


def build_machine_stats_embed(data, *, archived=False):
    """Titre daté pour distinguer clairement les anciennes semaines."""
    raw_week = data.get("week_start") or current_week_start()
    try:
        start = datetime.strptime(raw_week, "%Y-%m-%d").date()
    except ValueError:
        start = datetime.strptime(current_week_start(), "%Y-%m-%d").date()
    end = start + timedelta(days=6)

    users = data.get("users") or {}
    ranking = sorted(
        users.items(),
        key=lambda item: (-int(item[1].get("count", 0)), item[1].get("name", "").lower())
    )
    lines = [
        f"**{index}. {info.get('name', user_id)}** — `{int(info.get('count', 0))}` machine(s)"
        for index, (user_id, info) in enumerate(ranking, start=1)
    ]
    if not lines:
        lines = ["Aucune machine lancée cette semaine."]

    embed = discord.Embed(
        title=f"📊 Machines • Semaine du {start:%d/%m} au {end:%d/%m/%Y}",
        description="\n".join(lines),
    )
    embed.set_footer(
        text=(
            "📁 Classement archivé • Résultats définitifs"
            if archived else
            "🔄 Classement en cours • Mise à jour automatique"
        )
    )
    return embed


async def finalize_machine_stats_archive(previous_report):
    """Fige visuellement l'ancien message SANS le supprimer ni le remplacer."""
    if not MACHINE_STATS_CHANNEL_ID:
        return
    message_id = previous_report.get("message_id")
    if not message_id:
        return
    try:
        channel = bot.get_channel(MACHINE_STATS_CHANNEL_ID)
        if channel is None:
            channel = await bot.fetch_channel(MACHINE_STATS_CHANNEL_ID)
        if not isinstance(channel, discord.abc.Messageable):
            raise ValueError("Le salon Discord configuré ne permet pas les messages.")
        message = await channel.fetch_message(int(message_id))
        await message.edit(embed=build_machine_stats_embed(previous_report, archived=True))
        print(
            f"[MACHINES] Classement archivé : semaine={previous_report.get('week_start')} "
            f"message={message_id} (conservé)."
        )
    except discord.NotFound:
        print(f"[MACHINES] Ancien classement {message_id} introuvable (non supprimé par le bot).")
    except Exception as exc:
        # Une erreur d'édition de l'archive ne doit pas bloquer la nouvelle semaine.
        print(f"[MACHINES] Impossible de marquer l'ancien classement comme archivé : {exc}")


async def update_machine_stats_message():
    """Ne modifie QUE le message courant, sans doublon en cas d'accès simultané."""
    if not MACHINE_STATS_CHANNEL_ID:
        return
    async with MACHINE_STATS_MESSAGE_LOCK:
        data = load_machine_stats()
        channel = bot.get_channel(MACHINE_STATS_CHANNEL_ID)
        if channel is None:
            channel = await bot.fetch_channel(MACHINE_STATS_CHANNEL_ID)
        if not isinstance(channel, discord.abc.Messageable):
            raise ValueError("Le salon Discord configuré ne permet pas les messages.")

        embed = build_machine_stats_embed(data)
        message = None
        message_id = data.get("message_id")
        if message_id:
            try:
                message = await channel.fetch_message(int(message_id))
            except discord.NotFound:
                # Message supprimé manuellement : recréer seulement le courant.
                message = None
            except (ValueError, TypeError):
                message = None
            # Sur un 429/403/erreur réseau, ne PAS publier de doublon.

        # Une autre interaction peut avoir changé de semaine pendant un fetch.
        latest = load_machine_stats()
        if (latest.get("week_start") != data.get("week_start") or
                latest.get("message_id") != data.get("message_id")):
            return

        if message is None:
            message = await channel.send(embed=embed)
            # Ne jamais écraser un compteur modifié pendant l'envoi réseau.
            latest = load_machine_stats()
            if (latest.get("week_start") == data.get("week_start") and
                    not latest.get("message_id")):
                latest["message_id"] = str(message.id)
                save_machine_stats(latest)
            print(
                f"[MACHINES] Nouveau classement hebdomadaire : "
                f"semaine={data.get('week_start')} message={message.id}."
            )
        else:
            # Le classement peut avoir reçu un lancement pendant le fetch :
            # construire l'embed à partir de la version la plus récente.
            await message.edit(embed=build_machine_stats_embed(latest))


async def increment_machine_stat(member: discord.Member):
    data = load_machine_stats()
    week = current_week_start()
    previous_report = None

    if data.get("week_start") != week:
        # Même si une machine est lancée juste après minuit, on ne modifie
        # jamais le message de la semaine précédente.
        data, previous_report = start_new_machine_stats_report(data, week)

    uid = str(member.id)
    entry = data["users"].setdefault(uid, {"name": member.display_name, "count": 0})
    entry["name"] = member.display_name
    entry["count"] = int(entry.get("count", 0)) + 1
    save_machine_stats(data)

    if previous_report:
        await finalize_machine_stats_archive(previous_report)
    await update_machine_stats_message()


async def decrement_machine_stat(user_id: int, launched_at=None):
    data = load_machine_stats()
    # Une machine de la semaine précédente ne doit jamais modifier le
    # classement actuel, ni les archives qui sont définitives.
    if launched_at:
        try:
            launched = datetime.fromisoformat(str(launched_at))
            if launched.tzinfo is None:
                launched = launched.replace(tzinfo=TIMEZONE)
            launch_date = launched.astimezone(TIMEZONE).date()
            launch_week = (launch_date - timedelta(days=launch_date.weekday())).isoformat()
            if launch_week != data.get("week_start"):
                return
        except ValueError:
            pass

    uid = str(user_id)
    entry = data.get("users", {}).get(uid)
    if entry:
        entry["count"] = max(0, int(entry.get("count", 0)) - 1)
        if entry["count"] == 0:
            data["users"].pop(uid, None)
        save_machine_stats(data)
        await update_machine_stats_message()


async def machine_weekly_stats_reset_loop():
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            now = datetime.now(TIMEZONE)
            week = current_week_start()
            state = load_machine_weekly_reset_state()
            data = load_machine_stats()

            monday_after_reset = (
                now.weekday() == 0 and (now.hour, now.minute) >= (0, 5)
            )
            # Si le bot était éteint lundi, rattraper le reset mardi ou plus tard
            # uniquement quand le suivi montre une ancienne semaine.
            missed_reset = (
                now.weekday() > 0 and data.get("week_start") not in (None, week)
            )
            if state.get("week_start") != week and (monday_after_reset or missed_reset):
                archive_name, done = await reset_machine_week_everything()
                if done:
                    print(
                        f"[MACHINES] Reset hebdomadaire : {archive_name} "
                        f"à {datetime.now(TIMEZONE).strftime('%H:%M:%S')}"
                    )

            data = load_machine_stats()
            if data.get("week_start") is None:
                data["week_start"] = week
                save_machine_stats(data)

            # Si Discord était indisponible lors du reset, publier le nouveau
            # classement au redémarrage sans toucher aux anciens messages.
            if data.get("week_start") == week and not data.get("message_id"):
                await update_machine_stats_message()

        except Exception as exc:
            print(f"[RESET HEBDO MACHINES] {exc}")

        await asyncio.sleep(10)


def delete_machine_sheet_row(row: int):
    # Annulation : on conserve physiquement la ligne pour ne jamais casser
    # les formules de la colonne D (ou d'autres colonnes du tableau).
    ws = worksheet(MACHINES_SHEET_ID, MACHINES_WORKSHEET)
    row = int(row)

    # Le bot utilise uniquement B, C, E et H pour une machine.
    # D n'est jamais touchée.
    ws.batch_clear([
        f"B{row}",
        f"C{row}",
        f"E{row}",
        f"H{row}",
    ])


def latest_unrecovered_machine():
    """Retourne la dernière vraie machine encore marquée non récupérée."""
    reminders = load_reminders()
    candidates = [
        r for r in reminders
        if not r.get("is_test", False)
        and not r.get("recovered", False)
        and not r.get("suppress_auto_reminders", False)
    ]
    if not candidates:
        return None

    def sort_key(item):
        for field in ("launched_at", "finish_at"):
            raw = item.get(field)
            if raw:
                try:
                    return datetime.fromisoformat(raw)
                except Exception:
                    pass
        return datetime.min.replace(tzinfo=TIMEZONE)

    return max(candidates, key=sort_key)


def set_machine_recovered_state(reminder_id: str, recovered: bool, user_name: str):
    reminders = load_reminders()
    reminder = next((r for r in reminders if str(r.get("id")) == str(reminder_id)), None)
    if reminder is None:
        return None

    if reminder.get("cancelled", False):
        return None
    if bool(reminder.get("recovered", False)) == bool(recovered):
        return reminder  # Pas de nouveau timestamp pour un double clic.
    reminder["recovered"] = bool(recovered)
    now = datetime.now(TIMEZONE)

    if recovered:
        reminder["recovered_by"] = user_name
        reminder["recovered_at"] = now.isoformat()
    else:
        reminder.pop("recovered_by", None)
        reminder.pop("recovered_at", None)
        reminder["last_reminder_at"] = now.isoformat()
        reminder["finished_notified"] = True

    save_reminders(reminders)
    return reminder


def update_status_field_in_embed(embed: discord.Embed, recovered: bool):
    status = "🟢 **RÉCUPÉRÉE**" if recovered else "🔴 **NON RÉCUPÉRÉE**"
    found = False
    for index, field in enumerate(embed.fields):
        if "Statut" in (field.name or ""):
            embed.set_field_at(index, name=field.name, value=status, inline=field.inline)
            found = True
            break
    if not found:
        embed.add_field(name="📌 Statut", value=status, inline=False)
    return embed


async def refresh_known_machine_status_messages(reminder: dict, recovered: bool):
    """Met à jour les messages de fin/rappel connus pour garder le statut visuel synchronisé."""
    if not reminder:
        return
    channel_id = int(reminder.get("channel_id") or MACHINE_REMINDER_CHANNEL_ID)
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception:
            return
    if not isinstance(channel, discord.abc.Messageable):
        return

    message_ids = []
    for key in ("finish_message_id", "last_reminder_message_id"):
        value = reminder.get(key)
        if value:
            message_ids.append(str(value))

    for message_id in dict.fromkeys(message_ids):
        try:
            msg = await channel.fetch_message(int(message_id))
            if not msg.embeds:
                continue
            embed = msg.embeds[0]
            update_status_field_in_embed(embed, recovered)
            await msg.edit(
                embed=embed,
                view=MachineRecoveredView(str(reminder["id"]), recovered=recovered)
            )
        except Exception:
            pass


async def check_previous_machine_before_launch(interaction: discord.Interaction):
    """
    Ouvre directement le modal si aucune machine précédente n'attend.
    Sinon demande confirmation avant de permettre le nouveau lancement.
    """
    previous = latest_unrecovered_machine()
    if previous is None:
        await interaction.response.send_modal(MachineModal())
        return

    amount = int(previous.get("amount", 0))
    await interaction.response.send_message(
        "⚠️ **La machine précédente est encore marquée NON RÉCUPÉRÉE.**\n"
        f"💸 Montant lancé : **{format_money(amount)}**\n\n"
        "**La machine a-t-elle bien été récupérée ?**\n"
        "• **Oui** : elle passe en récupérée, ses rappels s'arrêtent et tu peux lancer la suivante.\n"
        "• **Non** : le nouveau lancement est annulé.",
        view=PreviousMachineRecoveryConfirmView(str(previous["id"])),
        ephemeral=True
    )


class PreviousMachineRecoveryConfirmView(discord.ui.View):
    def __init__(self, reminder_id: str):
        super().__init__(timeout=60)
        self.reminder_id = str(reminder_id)

    @discord.ui.button(label="Oui, récupérée", emoji="🟢", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, MACHINE_ROLES):
            await interaction.response.send_message("❌ Tu n'as pas l'autorisation.", ephemeral=True)
            return

        reminder = set_machine_recovered_state(
            self.reminder_id,
            True,
            interaction.user.display_name
        )
        if reminder is None:
            await interaction.response.send_message(
                "⚠️ La machine précédente n'existe plus dans le suivi.",
                ephemeral=True
            )
            return

        await refresh_known_machine_status_messages(reminder, True)
        sale_progress_request_refresh()
        await send_machine_log(
            f"🟢 **Machine précédente confirmée récupérée avant nouveau lancement**\n"
            f"👤 Par : **{interaction.user.display_name}**\n"
            f"📋 Référence dans le suivi : **{reminder.get('sheet_row', 'N/A')}**\n"
            f"🕒 Heure : **{datetime.now(TIMEZONE).strftime('%H:%M')}**"
        )
        await interaction.response.send_modal(MachineModal())

    @discord.ui.button(label="Non", emoji="🔴", style=discord.ButtonStyle.danger)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content=(
                "❌ **Nouveau lancement annulé.**\n"
                "La machine précédente reste marquée **NON RÉCUPÉRÉE** et les rappels continuent."
            ),
            view=None
        )


def corrected_machine_launch(old_launch: datetime, hour: int, minute: int) -> datetime:
    """Choisit le jour voisin qui garde la correction au plus près du lancement."""
    old_launch = old_launch.astimezone(TIMEZONE)
    same_day = old_launch.replace(hour=hour, minute=minute, second=0, microsecond=0)
    # Le jour courant reste prioritaire en cas d'égalité exacte (12 heures).
    candidates = (same_day, same_day - timedelta(days=1), same_day + timedelta(days=1))
    return min(candidates, key=lambda candidate: abs(candidate - old_launch))


class MachineTimeEditModal(discord.ui.Modal, title="Modifier l'heure de lancement"):
    time_input = discord.ui.TextInput(
        label="Nouvelle heure (Belgique)",
        placeholder="HH:MM - exemple : 21:35",
        required=True,
        max_length=5,
    )

    def __init__(self, reminder_id: str):
        super().__init__()
        self.reminder_id = str(reminder_id)

    async def on_submit(self, interaction: discord.Interaction):
        raw = str(self.time_input.value).strip()
        try:
            parsed = datetime.strptime(raw, "%H:%M")
        except ValueError:
            await interaction.response.send_message(
                "❌ Heure invalide. Utilise le format **HH:MM**, par exemple `21:35`.",
                ephemeral=True
            )
            return

        reminders = load_reminders()
        reminder = next(
            (r for r in reminders if str(r.get("id")) == self.reminder_id),
            None
        )
        if reminder is None:
            await interaction.response.send_message(
                "⚠️ Cette machine n'existe plus dans le suivi.",
                ephemeral=True
            )
            return

        try:
            launched_raw = reminder.get("launched_at")
            if launched_raw:
                old_launch = datetime.fromisoformat(launched_raw)
                if old_launch.tzinfo is None:
                    old_launch = old_launch.replace(tzinfo=TIMEZONE)
            else:
                old_finish = datetime.fromisoformat(reminder["finish_at"])
                if old_finish.tzinfo is None:
                    old_finish = old_finish.replace(tzinfo=TIMEZONE)
                old_launch = machine_time_shift(old_finish, -MACHINE_DURATION)

            new_launch = corrected_machine_launch(old_launch, parsed.hour, parsed.minute)
            new_finish = machine_time_shift(new_launch, MACHINE_DURATION)

            old_time = old_launch.strftime("%d/%m/%Y à %H:%M")
            reminder["launched_at"] = new_launch.isoformat()
            reminder["finish_at"] = new_finish.isoformat()

            row = reminder.get("sheet_row")
            if row is not None:
                await run_blocking(
                    update_machine_time_sheet, int(row),
                    new_launch.strftime("%H:%M"), new_launch.strftime("%d/%m/%Y")
                )

            save_reminders(reminders)

            old_task = reminder_tasks.pop(self.reminder_id, None)
            if old_task is not None and not old_task.done():
                old_task.cancel()
                try:
                    await old_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
            schedule_reminder(reminder)

            if interaction.message and interaction.message.embeds:
                embed = interaction.message.embeds[0]
                for index, field in enumerate(embed.fields):
                    if "Lancement" in (field.name or ""):
                        embed.set_field_at(
                            index,
                            name=field.name,
                            value=machine_display_time(new_launch),
                            inline=field.inline
                        )
                    elif "Fin prévue" in (field.name or ""):
                        embed.set_field_at(
                            index,
                            name=field.name,
                            value=machine_display_time(new_finish),
                            inline=field.inline
                        )
                await interaction.response.edit_message(
                    embed=embed,
                    view=MachineLaunchView(self.reminder_id, row)
                )
            else:
                await interaction.response.send_message("✅ Heure corrigée.", ephemeral=True)

            await send_machine_log(
                f"🕐 **Heure de machine modifiée**\n"
                f"👤 Par : **{interaction.user.display_name}**\n"
                f"⏰ Ancienne heure : **{old_time}**\n"
                f"⏰ Nouvelle heure : **{new_launch.strftime('%d/%m/%Y à %H:%M')}**\n"
                f"🏁 Nouveau rappel : **{new_finish.strftime('%d/%m/%Y à %H:%M')}**"
            )
        except Exception as exc:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ Erreur : `{exc}`", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Erreur : `{exc}`", ephemeral=True)


class MachineRelaunchView(discord.ui.View):
    def __init__(self, reminder_id: str):
        super().__init__(timeout=None)
        self.reminder_id = str(reminder_id)

        launch_again = discord.ui.Button(
            label="Lancer une machine",
            emoji="⚙️",
            style=discord.ButtonStyle.primary,
            custom_id=f"machine_relaunch_cancelled:{self.reminder_id}",
        )
        launch_again.callback = self.launch_again
        self.add_item(launch_again)

    async def launch_again(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, MACHINE_ROLES):
            await interaction.response.send_message(
                "❌ Tu n'as pas l'autorisation de lancer une machine.",
                ephemeral=True
            )
            return
        await check_previous_machine_before_launch(interaction)


class MachineLaunchView(discord.ui.View):
    def __init__(self, reminder_id: str, sheet_row=None):
        super().__init__(timeout=None)
        self.reminder_id = str(reminder_id)
        self.sheet_row = int(sheet_row) if sheet_row not in (None, "", "None") else None

        launch_again = discord.ui.Button(
            label="Lancer une machine",
            emoji="⚙️",
            style=discord.ButtonStyle.primary,
            custom_id=f"machine_launch_again:{self.reminder_id}",
        )
        launch_again.callback = self.launch_again
        self.add_item(launch_again)

        edit_time = discord.ui.Button(
            label="Modifier l'heure",
            emoji="🕐",
            style=discord.ButtonStyle.secondary,
            custom_id=f"machine_edit_time:{self.reminder_id}",
        )
        edit_time.callback = self.edit_time
        self.add_item(edit_time)

        cancel = discord.ui.Button(
            label="Annuler la machine",
            emoji="❌",
            style=discord.ButtonStyle.danger,
            custom_id=f"machine_cancel:{self.reminder_id}",
        )
        cancel.callback = self.cancel_machine
        self.add_item(cancel)

    async def launch_again(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, MACHINE_ROLES):
            await interaction.response.send_message("❌ Tu n'as pas l'autorisation.", ephemeral=True)
            return
        await check_previous_machine_before_launch(interaction)

    async def edit_time(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, MACHINE_ROLES):
            await interaction.response.send_message("❌ Tu n'as pas l'autorisation.", ephemeral=True)
            return
        await interaction.response.send_modal(MachineTimeEditModal(self.reminder_id))

    async def cancel_machine(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, MACHINE_ROLES):
            await interaction.response.send_message("❌ Tu n'as pas l'autorisation d'annuler une machine.", ephemeral=True)
            return

        # Réponse privée séparée : ne jamais transformer/supprimer la carte publique.
        await interaction.response.defer(ephemeral=True, thinking=True)

        # Remove the pending reminder first.
        reminders = load_reminders()
        cancelled_reminder = next(
            (r for r in reminders if str(r.get("id")) == self.reminder_id),
            None
        )
        # On conserve aussi l'historique des machines annulées : leurs anciens
        # messages doivent continuer à répondre après un reboot.
        if cancelled_reminder is not None:
            cancelled_reminder["cancelled"] = True
            cancelled_reminder["recovered"] = True
            cancelled_reminder["suppress_auto_reminders"] = True
            cancelled_reminder["cancelled_at"] = datetime.now(TIMEZONE).isoformat()
        save_reminders(reminders)
        sale_progress_request_refresh()

        # Si la fiche historique a pu être reliée à la semaine courante, on vide
        # B/C/E/H. Sinon on annule uniquement son suivi Discord : surtout ne jamais
        # deviner une ligne et risquer d'effacer une machine différente.
        if self.sheet_row is not None:
            try:
                await run_blocking(delete_machine_sheet_row, self.sheet_row)
            except Exception as exc:
                await send_machine_log(
                    f"⚠️ **Erreur lors de l'annulation d'une machine**\n"
                    f"👤 Par : **{interaction.user.display_name}**\n"
                    f"📄 Ligne concernée : **{self.sheet_row}**\n"
                    f"⚠️ Le rappel a été annulé mais les cellules B/C/E/H n'ont pas pu être vidées.\n"
                    f"Erreur : `{exc}`"
                )
                return

        if cancelled_reminder and cancelled_reminder.get("user_id"):
            await decrement_machine_stat(
                int(cancelled_reminder["user_id"]),
                launched_at=cancelled_reminder.get("launched_at"),
            )

        # Mark the Discord card as cancelled and remove its controls.
        if interaction.message and interaction.message.embeds:
            embed = interaction.message.embeds[0]
            embed.title = "❌ Machine annulée"
            embed.description = "Cette machine a été annulée. Aucun rappel ne sera envoyé."
            relaunch_view = MachineRelaunchView(self.reminder_id)
            bot.add_view(relaunch_view)
            await interaction.message.edit(
                embed=embed,
                view=relaunch_view
            )

        sheet_log = (
            f"📋 Données de la référence vidées : **{self.sheet_row}**"
            if self.sheet_row is not None
            else "📋 Ancienne fiche : aucune opération actuelle n'a été touchée."
        )
        await send_machine_log(
            f"❌ **Machine annulée**\n"
            f"👤 Par : **{interaction.user.display_name}**\n"
            f"{sheet_log}\n"
            f"🕒 Heure : **{datetime.now(TIMEZONE).strftime('%H:%M')}**"
        )


class MachineRecoveredView(discord.ui.View):
    def __init__(self, reminder_id: str, recovered: bool = False):
        super().__init__(timeout=None)
        self.reminder_id = str(reminder_id)
        self.recovered = bool(recovered)

        button = discord.ui.Button(
            label="Récupérée" if self.recovered else "Non récupérée",
            emoji="🟢" if self.recovered else "🔴",
            style=discord.ButtonStyle.success if self.recovered else discord.ButtonStyle.danger,
            custom_id=f"machine_recovered:{self.reminder_id}",
            disabled=False,
        )
        button.callback = self.toggle_recovered
        self.add_item(button)

        launch_again = discord.ui.Button(
            label="Lancer une machine",
            emoji="⚙️",
            style=discord.ButtonStyle.primary,
            custom_id=f"machine_recovered_launch:{self.reminder_id}",
        )
        launch_again.callback = self.launch_again
        self.add_item(launch_again)

    async def launch_again(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, MACHINE_ROLES):
            await interaction.response.send_message(
                "❌ Tu n'as pas l'autorisation de lancer une machine.",
                ephemeral=True
            )
            return
        await check_previous_machine_before_launch(interaction)

    async def toggle_recovered(self, interaction: discord.Interaction):
        """Change le statut en éditant le message PUBLIC, sans jamais le supprimer."""
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, MACHINE_ROLES):
            await interaction.response.send_message(
                "❌ Tu n'as pas l'autorisation de modifier le statut de cette machine.",
                ephemeral=True
            )
            return

        reminders = load_reminders()
        reminder = next(
            (r for r in reminders if str(r.get("id")) == self.reminder_id),
            None
        )
        if reminder is None:
            await interaction.response.send_message(
                "⚠️ Ce rappel n'existe plus dans le suivi du bot.",
                ephemeral=True
            )
            return

        if interaction.message is None:
            await interaction.response.send_message(
                "❌ Impossible de retrouver le message de cette machine.",
                ephemeral=True
            )
            return

        # Un vieux bouton ou un double clic ne doit pas inverser un état qui
        # vient juste d'être modifié depuis une autre carte Discord.
        if bool(reminder.get("recovered", False)) != self.recovered:
            await interaction.response.send_message(
                "⚠️ Le statut de cette machine a déjà changé depuis ce message. "
                "Utilise sa carte la plus récente pour éviter un double décompte.",
                ephemeral=True,
            )
            return
        if reminder.get("cancelled", False):
            await interaction.response.send_message(
                "❌ Cette machine est annulée.", ephemeral=True
            )
            return

        # Accusé de réception du CLIC sur le bouton, sans réponse éphémère
        # et sans appeler delete_original_response() sur le message public.
        await interaction.response.defer(thinking=False)

        old_state = dict(reminder)
        new_status = not self.recovered
        now = datetime.now(TIMEZONE)
        reminder["recovered"] = new_status
        if new_status:
            reminder["recovered_by"] = interaction.user.display_name
            reminder["recovered_at"] = now.isoformat()
        else:
            reminder.pop("recovered_by", None)
            reminder.pop("recovered_at", None)
            reminder["last_reminder_at"] = now.isoformat()
            reminder["finished_notified"] = True

        # Modifie explicitement le MÊME message Discord. Aucun message.delete(),
        # aucune réponse supprimée et aucun nouveau message public.
        embed = (
            interaction.message.embeds[0].copy()
            if interaction.message.embeds
            else discord.Embed(title="💰 Machine terminée")
        )
        update_status_field_in_embed(embed, new_status)
        try:
            await interaction.message.edit(
                embed=embed,
                view=MachineRecoveredView(self.reminder_id, recovered=new_status)
            )
            save_reminders(reminders)
            sale_progress_request_refresh()
        except Exception as exc:
            # Si Discord ou la sauvegarde échoue, on ne laisse pas un rappel
            # enregistré avec un statut différent de celui attendu.
            reminder.clear()
            reminder.update(old_state)
            try:
                save_reminders(reminders)
            except Exception as rollback_exc:
                print(f"[MACHINES] Impossible de restaurer le suivi : {rollback_exc}")
            await interaction.followup.send(
                f"❌ Impossible de mettre à jour cette machine : `{exc}`",
                ephemeral=True
            )
            return

        # Harmonise les autres messages de rappel déjà connus, toujours
        # par édition et jamais par suppression.
        try:
            await refresh_known_machine_status_messages(reminder, new_status)
        except Exception as exc:
            print(f"[MACHINES] Synchronisation des anciens rappels impossible : {exc}")

        status_text = "🟢 Récupérée" if new_status else "🔴 Non récupérée"
        test_text = " **[TEST]**" if reminder.get("is_test") else ""
        row_text = (
            f"\n📋 Référence dans le suivi : **{reminder.get('sheet_row')}**"
            if reminder.get("sheet_row") is not None else ""
        )
        print(
            f"[MACHINES] Message public {interaction.message.id} conservé ; "
            f"machine {self.reminder_id} : {status_text}"
        )
        try:
            await send_machine_log(
                f"🔄 **Statut machine modifié{test_text}**\n"
                f"👤 Par : **{interaction.user.display_name}**\n"
                f"📌 Nouveau statut : **{status_text}**"
                f"{row_text}\n"
                f"🕒 Heure : **{datetime.now(TIMEZONE).strftime('%H:%M')}**"
            )
        except Exception as exc:
            # Le changement de statut est déjà enregistré : une erreur de log
            # ne doit pas annuler la récupération ni faire disparaître la fiche.
            print(f"[MACHINES] Erreur de journalisation : {exc}")


class MachineWeeklyResetConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(
        label="Confirmer le reset",
        emoji="✅",
        style=discord.ButtonStyle.danger
    )
    async def confirm_reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, MACHINE_ROLES):
            await interaction.response.send_message(
                "❌ Tu n'as pas l'autorisation de reset la semaine.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            archive_name, done = await reset_machine_week_everything(manual=True)
            if not done:
                await interaction.followup.send(
                    "⚠️ Le reset de cette semaine a déjà été effectué.",
                    ephemeral=True
                )
                return

            await interaction.followup.send(
                f"✅ Reset effectué. Archive créée : **{archive_name}**.",
                ephemeral=True
            )
        except Exception as exc:
            await interaction.followup.send(
                f"❌ Impossible d'effectuer le reset : `{exc}`",
                ephemeral=True
            )

    @discord.ui.button(
        label="Annuler",
        emoji="❌",
        style=discord.ButtonStyle.secondary
    )
    async def cancel_reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="❌ Reset annulé.",
            view=None
        )


async def reset_machine_weekly_counter_only():
    """Remet uniquement à zéro le classement courant, sans effacer les archives."""
    data = load_machine_stats()
    week = current_week_start()
    previous_report = None
    if data.get("week_start") != week:
        data, previous_report = start_new_machine_stats_report(data, week)
    data["users"] = {}
    save_machine_stats(data)
    if previous_report:
        await finalize_machine_stats_archive(previous_report)
    await update_machine_stats_message()


class MachineCounterResetConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Oui, remettre à 0", emoji="✅",
                       style=discord.ButtonStyle.danger,
                       custom_id="machines:confirm_reset_counter")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, MACHINE_ROLES):
            await interaction.response.send_message(
                "❌ Tu n'as pas l'autorisation de reset le compteur.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await reset_machine_weekly_counter_only()
            await send_machine_log(
                f"🔄 **Compteur hebdomadaire Machines remis à 0**\n"
                f"👤 Par : **{interaction.user.display_name}**\n"
                f"🕒 Heure : **{datetime.now(TIMEZONE).strftime('%H:%M')}**\n"
                f"ℹ️ Suivi, machines en cours et rappels inchangés."
            )
            await interaction.edit_original_response(
                content="✅ Compteur hebdomadaire Machines remis à **0**.",
                view=None
            )
        except Exception as exc:
            await interaction.followup.send(
                f"❌ Impossible de remettre le compteur à 0 : `{exc}`", ephemeral=True
            )

    @discord.ui.button(label="Annuler", emoji="❌",
                       style=discord.ButtonStyle.secondary,
                       custom_id="machines:cancel_reset_counter")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Ferme uniquement la confirmation privée.
        await interaction.response.edit_message(
            content="❌ Reset compteur annulé.",
            view=None
        )


class MachinesPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        if "sales" not in globals().get("_tenant_runtime_active_modules", {"sales"}):
            for item in list(self.children):
                if getattr(item, "custom_id", None) in {"machines:add_employee", "machines:delete_employee"}:
                    self.remove_item(item)

    @discord.ui.button(
        label="Ajouter une personne", emoji="👤", style=discord.ButtonStyle.secondary,
        custom_id="machines:add_employee", row=1,
    )
    async def add_employee(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, MACHINE_ROLES):
            await interaction.response.send_message(
                "❌ Tu n'as pas l'autorisation de gérer les personnes.", ephemeral=True
            )
            return
        await interaction.response.send_modal(SaleChoiceModal(True))

    @discord.ui.button(
        label="Supprimer une personne", style=discord.ButtonStyle.danger,
        custom_id="machines:delete_employee", row=1,
    )
    async def delete_employee(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, MACHINE_ROLES):
            await interaction.response.send_message(
                "❌ Tu n'as pas l'autorisation de gérer les personnes.", ephemeral=True
            )
            return
        if not SALE_EMPLOYEES:
            await interaction.response.send_message("ℹ️ La liste est déjà vide.", ephemeral=True)
            return
        view = discord.ui.View(timeout=120)
        view.add_item(SaleChoiceDeleteSelect(True))
        await interaction.response.send_message(
            "Choisis la personne à supprimer de la liste commune aux panneaux Sale et Machines. "
            "Les anciennes fiches sont conservées.",
            view=view, ephemeral=True,
        )

    @discord.ui.button(
        label="Reset semaine",
        emoji="🔄",
        style=discord.ButtonStyle.danger,
        custom_id="machines:reset_week",
    )
    async def reset_week(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, MACHINE_ROLES):
            await interaction.response.send_message(
                "❌ Tu n'as pas l'autorisation de reset la semaine.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "⚠️ **Confirmer le reset de la semaine Machines ?**\n"
            "La feuille actuelle sera archivée en **Semaine X**, puis les données "
            "de `Blanchiments` et le classement hebdomadaire Discord seront remis à zéro.",
            view=MachineWeeklyResetConfirmView(),
            ephemeral=True
        )

    @discord.ui.button(
        label="Reset compteur",
        emoji="0️⃣",
        style=discord.ButtonStyle.secondary,
        custom_id="machines:reset_counter",
    )
    async def reset_counter(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, MACHINE_ROLES):
            await interaction.response.send_message(
                "❌ Tu n'as pas l'autorisation de reset le compteur.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "⚠️ **Remettre à 0 le nombre de machines lancées cette semaine ?**\n"
            "Cela ne touche **ni au suivi, ni aux machines en cours, ni aux rappels**.",
            view=MachineCounterResetConfirmView(),
            ephemeral=True
        )

    @discord.ui.button(
        label="Reset rappels",
        emoji="🧹",
        style=discord.ButtonStyle.danger,
        custom_id="machines:reset_reminders",
    )
    async def reset_reminders(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, MACHINE_ROLES):
            await interaction.response.send_message(
                "❌ Tu n'as pas l'autorisation de reset les rappels.",
                ephemeral=True
            )
            return

        # IMPORTANT : ne jamais supprimer les machines récupérées du JSON,
        # sinon leurs montants seraient perdus et la progression tomberait à 0 %.
        reminders = load_reminders()
        count = 0
        for reminder in reminders:
            if not reminder.get("suppress_auto_reminders", False):
                reminder["suppress_auto_reminders"] = True
                count += 1
        save_reminders(reminders)
        # Les timers actifs consultent ce drapeau après leur attente.
        await interaction.response.send_message(
            f"🧹 **{count} rappel(s) désactivé(s).**\n"
            "✅ L'historique des machines (dont les récupérations) est conservé "
            "pour le suivi des sales. Les opérations n'ont pas été modifiées.",
            ephemeral=True
        )

    @discord.ui.button(
        label="Tester le rappel",
        emoji="🔔",
        style=discord.ButtonStyle.secondary,
        custom_id="machines:test_reminder",
    )
    async def test_reminder(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ Cette action doit être utilisée sur le serveur.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, MACHINE_ROLES):
            await interaction.response.send_message(
                "❌ Tu n'as pas l'autorisation de tester les rappels.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        target = bot.get_channel(MACHINE_REMINDER_CHANNEL_ID)
        if target is None:
            target = await bot.fetch_channel(MACHINE_REMINDER_CHANNEL_ID)
        if not isinstance(target, discord.abc.Messageable):
            raise ValueError("Le salon Discord configuré ne permet pas les messages.")
        role = machine_reminder_role(interaction.guild)
        if role is None:
            await interaction.followup.send("❌ Rôle **Employés** introuvable.", ephemeral=True)
            return
        test_id = f"test-{int(datetime.now(TIMEZONE).timestamp() * 1000)}"

        await target.send(
            f"🔔 {role.mention} **Machine terminée !**\n"
            "⏱️ Les **4h45** sont écoulées. La machine peut être récupérée.\n"
            "🧪 *Ceci est un test du rappel.*",
            allowed_mentions=discord.AllowedMentions(roles=True),
            view=MachineRecoveredView(test_id, recovered=False)
        )

        reminders = load_reminders()
        now = datetime.now(TIMEZONE)
        reminders.append({
            "id": test_id,
            "channel_id": MACHINE_REMINDER_CHANNEL_ID,
            "user_id": interaction.user.id,
            "amount": 0,
            "finish_at": now.isoformat(),
            "sheet_row": None,
            "recovered": False,
            "finished_notified": True,
            "last_reminder_at": now.isoformat(),
            "is_test": True,
        })
        save_reminders(reminders)

    @discord.ui.button(
        label="Machine lancée",
        emoji="⚙️",
        style=discord.ButtonStyle.success,
        custom_id="panel:machine_started",
    )
    async def machine_started(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user, MACHINE_ROLES):
            await interaction.response.send_message("❌ Tu n'as pas l'autorisation de lancer une machine.", ephemeral=True)
            return
        await check_previous_machine_before_launch(interaction)


async def restore_machine_panels_after_restart():
    """Actualise les panneaux Machines existants sans recréer de message."""
    await bot.wait_until_ready()
    try:
        channel = bot.get_channel(MACHINES_CHANNEL_ID) or await bot.fetch_channel(MACHINES_CHANNEL_ID)
        if not isinstance(channel, discord.abc.Messageable):
            raise ValueError("Le salon Machines configuré ne permet pas les messages.")
        async for message in channel.history(limit=None):
            if not bot.user or message.author.id != bot.user.id:
                continue
            ids = set(_machine_message_component_ids(message))
            if "panel:machine_started" not in ids:
                continue
            bot.add_view(MachinesPanel(), message_id=message.id)
            expected_ids = {item.custom_id for item in MachinesPanel().children}
            if ids == expected_ids:
                continue
            await sale_restore_edit(message, MachinesPanel())
            print(f"[MACHINES] Panneau {message.id} actualisé selon la configuration du serveur.", flush=True)
    except Exception as exc:
        print(f"[MACHINES] Actualisation des panneaux impossible : {exc}", flush=True)


async def reminder_worker(reminder: dict):
    reminder_id = str(reminder["id"])
    try:
        finish = datetime.fromisoformat(reminder["finish_at"])
        if finish.tzinfo is None:
            finish = finish.replace(tzinfo=TIMEZONE)

        now = datetime.now(TIMEZONE)
        seconds = max(0, (finish.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds())
        await asyncio.sleep(seconds)

        # Recharge l'état actuel : la machine a pu être annulée pendant l'attente.
        reminders = load_reminders()
        current = next(
            (r for r in reminders if str(r.get("id")) == reminder_id),
            None
        )
        if (current is None or current.get("recovered", False)
                or current.get("suppress_auto_reminders", False)
                or current.get("cancelled", False)):
            return

        guild = bot.get_guild(GUILD_ID)
        if guild is None:
            return

        channel = bot.get_channel(MACHINE_REMINDER_CHANNEL_ID)
        if channel is None:
            channel = await bot.fetch_channel(MACHINE_REMINDER_CHANNEL_ID)
        if not isinstance(channel, discord.abc.Messageable):
            raise ValueError("Le salon Discord configuré ne permet pas les messages.")

        role = machine_reminder_role(guild)
        if role is None:
            await send_machine_log(
                f"⚠️ **Rappel machine impossible**\\n"
                f"Le rôle **{MACHINE_REMINDER_ROLE_NAME}** est introuvable."
            )
            return

        amount = int(current.get("amount", 0))
        amount_to_collect = int(amount * 0.80)

        embed = discord.Embed(
            title="💰 Machine terminée",
            description=(
                "Le cycle de blanchiment est terminé.\\n"
                "La machine est maintenant **prête à être récupérée**."
            )
        )
        embed.add_field(
            name="💵 Montant lancé",
            value=f"**{format_money(amount)}**",
            inline=True
        )
        embed.add_field(
            name="💸 À récupérer",
            value=f"**{format_money(amount_to_collect)}**",
            inline=True
        )
        embed.add_field(
            name="📌 Statut",
            value="🔴 **NON RÉCUPÉRÉE**",
            inline=False
        )
        embed.set_footer(
            text="Une fois récupérée, cliquez sur le bouton ci-dessous."
        )

        msg = await channel.send(
            content=f"🔔 {role.mention} **Une machine est prête !**",
            embed=embed,
            view=MachineRecoveredView(reminder_id, recovered=False),
            allowed_mentions=discord.AllowedMentions(roles=True)
        )

        # Conserve le rappel pour permettre le statut et les relances toutes les 15 min.
        current["finished_notified"] = True
        current["last_reminder_at"] = datetime.now(TIMEZONE).isoformat()
        current["finish_message_id"] = str(msg.id)
        mids = current.setdefault("message_ids", [])
        if str(msg.id) not in {str(x) for x in mids}:
            mids.append(str(msg.id))

        latest = load_reminders()
        for index, item in enumerate(latest):
            if str(item.get("id")) == reminder_id:
                latest[index] = current
                break
        save_reminders(latest)

        launcher_name = "Utilisateur inconnu"
        try:
            launcher = guild.get_member(int(current.get("user_id")))
            if launcher is not None:
                launcher_name = launcher.display_name
        except Exception:
            pass

        await send_machine_log(
            f"🔔 **Machine terminée**\\n"
            f"👤 Lancée par : **{launcher_name}**\\n"
            f"💵 Montant lancé : **{format_money(amount)}**\\n"
            f"💸 À récupérer : **{format_money(amount_to_collect)}**\\n"
            f"📌 Statut : **🔴 Non récupérée**"
        )

    except asyncio.CancelledError:
        raise
    except Exception as exc:
        try:
            await send_machine_log(
                f"⚠️ **Erreur rappel machine**\\n"
                f"ID : `{reminder_id}`\\n"
                f"Erreur : `{exc}`"
            )
        except Exception:
            print(f"[RAPPEL MACHINE] {exc}")
    finally:
        reminder_tasks.pop(reminder_id, None)


def schedule_reminder(reminder: dict):
    reminder_id = reminder["id"]
    if reminder_id not in reminder_tasks:
        reminder_tasks[reminder_id] = asyncio.create_task(reminder_worker(reminder))


async def weekly_sales_reset_worker():
    """Check every minute and reset once each Monday at 00:00 Brussels time."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        now = datetime.now(TIMEZONE)
        state = load_weekly_reset_state()
        today = now.strftime("%Y-%m-%d")
        try:
            publish_sales_reset_site_state(state)
        except Exception as exc:
            print(f"[SALE] Signal du reset pour le site indisponible : {exc}")

        if now.weekday() == 0 and now.hour == 0 and state.get("last_reset_date") != today:
            try:
                archive_name = await run_blocking(reset_sales_week_sheet)
                save_weekly_reset_state(today, archive_name, automatic=True)
                print(f"Reset hebdomadaire Sales effectué : En cours -> {archive_name}")
            except Exception as exc:
                print(f"Erreur reset hebdomadaire Sales : {exc}")

        await asyncio.sleep(60)


async def machine_recovery_repeat_loop():
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            reminders = load_reminders()
            now = datetime.now(TIMEZONE)
            changed = False

            for reminder in list(reminders):
                if reminder.get("recovered", False):
                    continue
                # Les anciennes fiches reconstruites servent à refaire fonctionner
                # leurs boutons, pas à réveiller des rappels vieux de plusieurs mois.
                if reminder.get("suppress_auto_reminders", False):
                    continue

                try:
                    finish_at = datetime.fromisoformat(reminder["finish_at"])
                    if finish_at.tzinfo is None:
                        finish_at = finish_at.replace(tzinfo=TIMEZONE)
                except Exception:
                    continue

                if now < finish_at:
                    continue

                last_raw = reminder.get("last_reminder_at")
                if last_raw:
                    try:
                        last_at = datetime.fromisoformat(last_raw)
                        if last_at.tzinfo is None:
                            last_at = last_at.replace(tzinfo=TIMEZONE)
                        if (now - last_at).total_seconds() < 15 * 60:
                            continue
                    except Exception:
                        pass
                elif reminder.get("finished_notified", False):
                    # Legacy finished reminder without timestamp: start its 15-min clock now.
                    reminder["last_reminder_at"] = now.isoformat()
                    changed = True
                    continue

                guild = bot.get_guild(GUILD_ID)
                if guild is None:
                    continue

                channel = bot.get_channel(MACHINE_REMINDER_CHANNEL_ID)
                if channel is None:
                    channel = await bot.fetch_channel(MACHINE_REMINDER_CHANNEL_ID)
                if not isinstance(channel, discord.abc.Messageable):
                    raise ValueError("Le salon Discord configuré ne permet pas les messages.")

                role = machine_reminder_role(guild)
                if role is None:
                    continue

                amount = int(reminder.get("amount", 0))
                amount_to_collect = int(amount * 0.80)

                repeat_embed = discord.Embed(
                    title="⏰ Rappel • Machine non récupérée",
                    description="Cette machine attend toujours d'être récupérée."
                )
                repeat_embed.add_field(
                    name="💸 À récupérer",
                    value=f"**{format_money(amount_to_collect)}**",
                    inline=True
                )
                repeat_embed.add_field(
                    name="📌 Statut",
                    value="🔴 **NON RÉCUPÉRÉE**",
                    inline=True
                )
                repeat_embed.set_footer(
                    text="Cliquez sur le bouton lorsque la machine est récupérée."
                )

                repeat_msg = await channel.send(
                    content=f"🔔 {role.mention} **Rappel machine**",
                    embed=repeat_embed,
                    view=MachineRecoveredView(str(reminder["id"]), recovered=False),
                    allowed_mentions=discord.AllowedMentions(roles=True)
                )
                reminder["last_reminder_message_id"] = str(repeat_msg.id)
                mids = reminder.setdefault("message_ids", [])
                if str(repeat_msg.id) not in {str(x) for x in mids}:
                    mids.append(str(repeat_msg.id))
                reminder["finished_notified"] = True
                reminder["last_reminder_at"] = now.isoformat()
                changed = True

            if changed:
                save_reminders(reminders)

        except Exception as exc:
            print(f"[RAPPEL 15 MIN] {exc}")

        await asyncio.sleep(60)


# =========================
# TOMBOLA VEHICULES
# =========================
INITIAL_VEHICLE_CATALOG = {'voitures': ['Asbo', 'Blista', 'Brioso', 'Brioso 300', 'Brioso 300 Large', 'Club', 'Dilettante', 'Issi', 'Issi Classic', 'Kanjo', 'Panto', 'Prairie', 'Rhapsody', 'Weevil', 'Cognoscenti Cabrio', 'Exemplar', 'F620', 'Felon', 'Felon GT', 'Jackal', 'Oracle', 'Oracle XS', 'Previon', 'Sentinel', 'Sentinel XS', 'Windsor', 'Windsor Drop', 'Zion', 'Zion Cabrio', 'Kanjo SJ', 'Postlude', 'FR36 Drift', 'FR36', 'Euros X 32', 'Asea', 'Ariant', 'Asterope', 'Cognoscenti', 'Cognoscenti 55', 'Emperor', 'Emperor Rouillé', 'Fugitive', 'Glendale', 'Glendale Custom', 'Ingot', 'Intruder', 'Premier', 'Primo', 'Primo Custom', 'Regina', 'Schafter', 'Schafter LWB', 'Schafter V12', 'Stafford', 'Stanier', 'Stratum', 'Stretch', 'Super Diamond', 'Surge', 'Tailgater', 'Tailgater S', 'Warrener', 'Warrener H K R', 'Washington', 'Cinquemila', 'Deity', 'Ubermarcht Rhinehart', 'Seraph', 'Scharmann', 'Asterpe GZ', 'Minimus', 'Hardy Way', 'Chavos V6', 'Sentinel X S4', 'BF Echelon S', 'BF Echelon', 'Drafter', '9F', '9F Cabrio', 'Alpha', 'Banshee', 'Bestia GT S', 'Blista Compact', 'Buffalo', 'Buffalo S', 'Buffalo S T X', 'Calico G T F', 'Carbonizzare', 'Comet', 'Comet Retro Custom', 'Comet SR', 'Comet S2', 'Comet Safari', 'Coquette', 'Coquette D10', 'Cypher', 'Elegy Retro Custom', 'Elegy RH8', 'Euros', 'Feltzer', 'Flash GT', 'Furore GT', 'Fusilade', 'Futo', 'Futo GTX', 'GB 200', 'Growler', 'Imorgon', 'Issi Sport', 'Jester', 'Jester (Racecar)', 'Jester Classic', 'Jester RR', 'Jugular', 'Khamelion', 'Komoda', 'Kuruma', 'Sunrise', 'Locust', 'Lynx', 'Massacro', 'Massacro (Racecare)', 'Neo', 'Neon', 'Omnis', 'Paragon R', 'Pariah', 'Penumbra', 'Penumbra FF', 'Raiden', 'Rapid GT', 'Rapid GT Convertible', 'Raptor', 'Remus', 'RT 3000', 'Ruston', 'Schlagen', 'Schwartzer', 'Sentinel Classic', 'Seven 70', 'Specter', 'Specter Custom', 'Sugoi', 'Sultan', 'Sultan Classic', 'Sultan RS Classic', 'Surano', 'Tampa Drift', 'Tropos', 'Vectre', 'Verlierer', 'V-S T R', 'ZR 350', 'Sentinel Classic Large', 'Bénéfactor Sm 722', 'Corsita Lampadati', 'Obey 10F', 'Obey 10F Large', 'Buffalo Sprunk', 'Hotrinf Everon', 'Hotring Sabre', 'Panthere', '300 R', 'Coureur', 'Hotring Hellfire', 'Itali G T O Stinger T T', 'Euros Drift', 'Futo G T X Drift', 'Jester R R Drift', 'Remus Drift', 'ZR 350 Drift', 'Rapid GT X', 'Sentinel G T S', 'Jester RR Widebody', 'Banshee G T S', 'Coquette D5', 'Envisage', 'Paragon S', 'Obey Argento 2F', 'Annis Rumina', 'Annis Romulus', 'Annis Mochi', 'Maibatsu Arsher Pro 2', 'Casco', 'Cheburek', 'Cheetah Classic', 'Coquette Classic', 'Dynasty', 'Fagaola', 'Infernus Classic', 'Mamba', 'Manana', 'Michelli GT', 'Monroe', 'Nebula Turbo', 'Peyote', 'Peyote Custom', 'Pigalle', 'Rapid GT Classic', 'Retinue', 'Retinue MK 2', 'Roosvelt', 'Roosvelt Valor', 'Stinger', 'Stinger GT', 'Stirling GT', 'Torero', 'Tornado Custom', 'Tornado Rouillé', 'Turismo Classic', 'Zion Classic', 'Z-type', 'Frânken Strange', 'GT 500', 'JB 700 W', 'Savestra', 'Swinger', 'Tornado', 'Tornado Cabrio', 'Tornado Cabrio Rouillé', 'Tornado Rat-Rod', 'Viseris', '190 Z', 'Cheetah Classic LSCM', 'Uranus LozSpeed', 'Coquette D1', 'GT750', 'Itali Classic', 'Astrale', 'Annis Elegy RH-2', 'Adder', 'Autarch', 'Banshee 900 R', 'Bullet', 'Cheetah', 'Cyclone', 'Emerus', 'Entity X F', 'Entity XX R', 'E T R 1', 'F M J', 'Furia', 'GP 1', 'Infernus', 'Itali GTB', 'Itali G T O', 'Itali G T B Custom', 'Itali R S X', 'Krieger', 'Nero', 'Nero Custom', 'Osiris', 'Penetrator', 'Pfister 811', 'R E - 7B', 'Reaper', 'SC 1', 'Sultan RS', 'T 20', 'Taipan', 'Tempesta', 'Tezeract', 'Thrax', 'Tigon', 'Turismo R', 'Tyrant', 'Tyrus', 'Vacca', 'Vagner', 'Visione', 'Voltic', 'X80 Proto', 'X A 21', 'Zentorno', 'Zorusso', 'Zeno', 'Ignus', 'Comet S2 Cabrio', 'Champion', 'Benefactor LM 87', 'Torero XO', 'Omnis e-GT', 'Deveste', 'Entity MT', 'S80 RR', 'Virtue', 'Turismo Omaggio', 'Suzume', 'Pipistrello', 'Thrax Venuum', 'FMJ MK V', 'Luiva', 'X-treme', 'Blade', 'Buccaneer', 'Buccaneer Rider', 'Chino', 'Chino Luxe', 'Clique', 'Coquette Black Fin', 'Deviant', 'Dominator', 'Dominator GTT', 'Dominator GTX', 'Dominator ASP', 'Dukes', 'Ellie', 'Faction', 'Faction Rider', 'Faction XL', 'Gauntlet', 'Gauntlet Classic', 'Gauntlet Classic Custom', 'Gauntlet Hellfire', 'Hermes', 'Hotknife', 'Hustler', 'Impaler', 'Manana Custom', 'Nightshade', 'Phoenix', 'Picador', 'Rat-trucl', 'Ruiner', 'Sabre GT', 'Sabre Turbo', 'Slam Van', 'Slam Van du Lost', 'Slam Van Custom', 'Stallion', 'Tampa', 'Tulip', 'Vamos', 'Virgo', 'Virgo Classique Custom', 'Vigero', 'Voodoo Custom', 'Yosemite', 'Ruiner ZZ-8', 'BF Weevil Custom', 'Bravado Greenwood', 'Déclasse Vigero ZX', 'Broadway Classic', 'Dominator Pisswasser', 'Eudora', 'Gauntlet Redwood', 'Rat Loader', 'Tahoma Coupé', 'Tulip M-100', 'Voodoo', 'Peyote Gasser', 'Virgo Classic', 'Brigham', 'Bufallo E V X', 'Clique Wagon', 'Dominator GT', 'Yosemite Drift', 'Impaler5', 'Impaler LX', 'Vigero ZX Convertible', 'Tampa GT', 'Dominator F X', 'Brute Hurricane', 'Declasse Impaler Deluxe', 'Declasse Vigero Rattler', 'BF Injection', 'Bifta', 'Bodhi', 'Brawler', 'Caracara 4x4', 'Dubsta 6x6', 'Dune Buggy', 'Duneloader', 'Everon', 'Freecrawler', 'Hellion', 'Kalahari', 'Kamacho', 'Mesa Trail', 'Outlaw', 'Rancher XL', 'Rebel Rouillé', 'Rebel', 'Riata', 'Sandking XL', 'Sandking', 'Trophy Truck', 'Buggy Raid', 'Vagrant', 'Winky', 'Yosemite Rancher', 'Draugur', 'Boor', 'Walton L35', 'Monstro Citi', 'Ratel', 'Terminus', 'Walton L35 Stock', 'Firebolt ASP', 'Yosemite 1500', 'Baller', 'Baller ST', 'Baller II', 'Baller LBW', 'Baller Sport', 'BeeJay XL', 'Cavalcade', 'Cavalcade II', 'Contender', 'Dubsta', 'Dubsta Luxuary', 'Fhatom', 'Granger', 'Granger 3600 XL', 'Gresley', 'Habanero', 'Huntley S', 'Landstalker', 'Landstalker XL', 'Mesa', 'Novak', 'Patriot', 'Patriot Mil-Spec', 'Patriot Limo', 'Radius', 'Rebla GTS', 'Rocoto', 'Sadler', 'Seminole', 'Seminole Frontier', 'Serrano', 'Toros', 'Astron', 'XLS', 'Streiter', 'Jubilee', 'Gresleyh', 'Issi Rally', 'I-Wagen', 'Aleutian', 'Baller St-D', 'Cavalcade XL', 'Dorado', 'Vivanite', 'Woodlander', 'Everon RS', 'Castigator', 'Bison', 'Bobcat XL', 'Burrito', 'Burrito Custom', 'Burrito Du Lost', 'Camper', 'Journey', 'Minivan', 'Minivan Custom', 'Moonbeam', 'Moonbeam Rider', 'Pony', 'Pony Green', 'Paradise', 'Rumpo', 'Rumpo Trail', 'Speedo', 'Speedo Custom', 'Surfer', 'Surfer Rouillé', 'Youga', 'Youga Classic', 'Youga Classic 4X4', 'Guardian', 'Journey II', 'Youga Custom', 'Surfer Custom', 'Speedo Custom 2', 'Esperta', 'Voyager', 'Voyager 2', 'Bison S T X', 'Vapid Steed', 'BF e-Surfer', 'Caddy', 'Keitora'], 'motos': ['Zombie Bobber', 'Nightblade', 'Blazer Street', 'Blazer Custom', 'Blazer', 'Shinobi', 'Manchez Scout', 'Zombie Chopper', 'Wolfsbane', 'Vortex', 'Vader', 'Thrust', 'Sanctus', 'Sanchez', 'Sanchez Couleurs', 'Ruffian', 'Rat Bike', 'PCJ600', 'Gargoyle', 'Nemesis', 'Powersurge', 'Manchez Scout C', 'Manchez', 'Innovation', 'Stryder', 'Sovereign', 'Reever', 'Hexer', 'Hakuchou Drag', 'Hakuchou', 'FCR1000 Custom', 'FCR1000', 'Faggio Mod', 'Faggio', 'Faggio Sport', 'Esskey', 'Double-T', 'Enduro', 'Diabolous', 'Diabolus Custom', 'Defiler', 'Daemon Custom', 'Daemon', 'Cliffhanger', 'Chimera', 'Carbon RS', 'Bati 801 RR', 'BF400', 'Bagger', 'Bati 801', 'Avarus', 'Akuma']}

def _load_json_file(path: Path, default):
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as exc:
        print(f"Erreur lecture {path}: {exc}")
    return default

def _save_json_file(path: Path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)

def load_vehicle_catalog():
    if not VEHICLE_CATALOG_FILE.exists():
        _save_json_file(VEHICLE_CATALOG_FILE, INITIAL_VEHICLE_CATALOG)
    data = _load_json_file(VEHICLE_CATALOG_FILE, INITIAL_VEHICLE_CATALOG)
    data.setdefault("voitures", [])
    data.setdefault("motos", [])
    return data

def save_vehicle_catalog(data):
    data["voitures"] = sorted(set(data.get("voitures", [])), key=str.casefold)
    data["motos"] = sorted(set(data.get("motos", [])), key=str.casefold)
    _save_json_file(VEHICLE_CATALOG_FILE, data)

def week_key_from_date(d):
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return monday.isoformat(), monday, sunday

def current_tombola_week_key():
    return week_key_from_date(datetime.now(TIMEZONE).date())[0]

def load_tombola_data():
    data = _load_json_file(TOMBOLA_DATA_FILE, {"selected_week": current_tombola_week_key(), "weeks": {}})
    data.setdefault("selected_week", current_tombola_week_key())
    data.setdefault("weeks", {})
    return data

def save_tombola_data(data):
    _save_json_file(TOMBOLA_DATA_FILE, data)

def get_tombola_week(data, key=None):
    key = key or data.get("selected_week") or current_tombola_week_key()
    monday = datetime.fromisoformat(key).date()
    sunday = monday + timedelta(days=6)
    week = data["weeks"].setdefault(key, {
        "start": monday.isoformat(), "end": sunday.isoformat(),
        "vehicle1": None, "vehicle2": None, "extra": None
    })
    return key, week

def tombola_embed():
    data = load_tombola_data()
    key, week = get_tombola_week(data)
    save_tombola_data(data)
    start = datetime.fromisoformat(week["start"]).strftime("%d/%m/%Y")
    end = datetime.fromisoformat(week["end"]).strftime("%d/%m/%Y")
    embed = discord.Embed(
        title="🎟️ Véhicules Tombola",
        description=f"📅 **Semaine du {start} au {end}**"
    )
    total = paid = 0
    for slot, title in (("vehicle1", "Véhicule 1"), ("vehicle2", "Véhicule 2"), ("extra", "Véhicule supplémentaire")):
        item = week.get(slot)
        if not item:
            value = "*Non défini*" if slot != "extra" else "*Aucun*"
        else:
            price = int(item.get("price", 0))
            total += price
            if item.get("paid", False):
                paid += price
            icon = "🚗" if item.get("type") == "voiture" else "🏍️"
            buy = "🟢 Acheté" if item.get("bought", False) else "🟠 À acheter"
            pay = "🟢 Payé" if item.get("paid", False) else "🔴 En attente de paiement"
            value = f"{icon} **{item.get('name','?')}**\n💵 {format_money(price)}\n🛒 {buy}\n💳 {pay}"
        embed.add_field(name=title, value=value, inline=False)
    embed.add_field(name="💰 Total", value=f"**{format_money(total)}**", inline=True)
    embed.add_field(name="✅ Déjà payé", value=f"**{format_money(paid)}**", inline=True)
    embed.add_field(name="💸 Reste à payer", value=f"**{format_money(total-paid)}**", inline=True)
    embed.set_footer(text="Les statuts et montants sont modifiables à tout moment.")
    return embed

async def tombola_refresh_message(interaction):
    if interaction.message:
        try:
            await interaction.message.edit(embed=tombola_embed(), view=TombolaPanel())
        except discord.HTTPException:
            pass

def tombola_allowed(interaction):
    return isinstance(interaction.user, discord.Member) and has_role(interaction.user, TOMBOLA_ROLES)


TOMBOLA_DRAFTS = {}

def new_tombola_draft():
    _, monday, sunday = week_key_from_date(datetime.now(TIMEZONE).date())
    return {"start": monday.isoformat(), "end": sunday.isoformat(), "vehicles": [None, None]}

def tombola_draft_embed(draft):
    s=datetime.fromisoformat(draft["start"]).strftime("%d/%m/%Y")
    e=datetime.fromisoformat(draft["end"]).strftime("%d/%m/%Y")
    em=discord.Embed(title="🎟️ Préparation Tombola",description=f"📅 **Semaine du {s} au {e}**\nConfigure les véhicules puis clique sur **Valider**.")
    for i,v in enumerate(draft["vehicles"],1):
        if v:
            ico="🚗" if v["type"]=="voiture" else "🏍️"
            prix_affiche = f"**{format_money(v['price'])}**" if v.get("price") is not None else "🟡 **EN ATTENTE DE PRIX**"
            em.add_field(name=f"{ico} Véhicule {i}",value=f"**{v['name']}**\nType : {'Voiture' if v['type']=='voiture' else 'Moto'}\nPrix : {prix_affiche}",inline=False)
        else: em.add_field(name=f"Véhicule {i}",value="*À configurer*",inline=False)
    return em


def tombola_vehicle_embed(record, index):
    v = record["vehicles"][index]
    start = datetime.fromisoformat(record["start"])
    end = datetime.fromisoformat(record["end"])

    # ISO week number gives a stable "Semaine X".
    week_no = start.isocalendar().week
    icon = "🚗" if v["type"] == "voiture" else "🏍️"
    achat = "🟢 **ACHETÉ**" if v.get("bought", False) else "🟠 **À ACHETER**"
    paiement = "🟢 **PAYÉ**" if v.get("paid", False) else "🔴 **EN ATTENTE DE PAIEMENT**"

    embed = discord.Embed(
        title=f"{icon} VÉHICULE {index + 1} TOMBOLA • 📅 Semaine {week_no}",
        description=(
            f"📅 **Semaine du {start.strftime('%d/%m')} au {end.strftime('%d/%m')}**\n\n"
            f"{icon} **{v['name']}**\n"
            f"💰 Prix : **{format_money(int(v['price']))}**"
        )
    )
    # Two inline fields so Achat / Paiement sit next to each other.
    embed.add_field(name="📌 Achat", value=achat, inline=True)
    embed.add_field(name="💳 Paiement", value=paiement, inline=True)
    return embed


async def refresh_tombola_vehicle_message(record, index):
    try:
        message_ids = record.get("message_ids", [])
        if index >= len(message_ids) or not message_ids[index]:
            return
        channel = bot.get_channel(int(record["channel_id"])) or await bot.fetch_channel(int(record["channel_id"]))
        if not isinstance(channel, discord.abc.Messageable):
            raise ValueError("Le salon Discord configuré ne permet pas les messages.")
        msg = await channel.fetch_message(int(message_ids[index]))
        await msg.edit(
            embed=tombola_vehicle_embed(record, index),
            view=TombolaVehicleStatusView(record["id"], index)
        )
    except Exception as exc:
        print(f"Erreur refresh tombola véhicule {index + 1}: {exc}")


def tombola_global_embed(record):
    vehicles = record.get("vehicles", [])
    start = datetime.fromisoformat(record["start"])
    end = datetime.fromisoformat(record["end"])
    week_no = start.isocalendar().week

    total = sum(int(v["price"]) for v in vehicles if v.get("price") is not None)
    paid_total = sum(int(v["price"]) for v in vehicles if v.get("paid", False) and v.get("price") is not None)
    remaining = max(0, total - paid_total)
    missing_price = any(v.get("price") is None for v in vehicles)

    lines = []
    for i, v in enumerate(vehicles):
        icon = "🚗" if v.get("type") == "voiture" else "🏍️"
        achat = "🟢 **ACHETÉ**" if v.get("bought", False) else "🟠 **À ACHETER**"
        paiement = "🟢 **PAYÉ**" if v.get("paid", False) else "🔴 **EN ATTENTE**"
        prix = f"**{format_money(int(v['price']))}**" if v.get("price") is not None else "🟡 **EN ATTENTE DE PRIX**"
        lines.append(f"{icon} **Véhicule {i+1} : {v.get('name','Inconnu')}** • {prix} • {achat}  {paiement}")

    suffix = " + prix en attente" if missing_price else ""
    return discord.Embed(
        title=f"💰 TOTAL TOMBOLA • 📅 Semaine {week_no}",
        description=(
            f"📅 **Semaine du {start.strftime('%d/%m')} au {end.strftime('%d/%m')}**\n\n"
            + "\n".join(lines) + "\n\n"
            f"💰 **Prix global : {format_money(total)}{suffix}**\n"
            f"✅ **Déjà payé : {format_money(paid_total)}**\n"
            f"💳 **Reste à payer : {format_money(remaining)}{suffix}**"
        )
    )


async def refresh_tombola_global_message(record):
    try:
        mid = record.get("global_message_id")
        if not mid:
            return
        channel = bot.get_channel(int(record["channel_id"])) or await bot.fetch_channel(int(record["channel_id"]))
        if not isinstance(channel, discord.abc.Messageable):
            raise ValueError("Le salon Discord configuré ne permet pas les messages.")
        msg = await channel.fetch_message(int(mid))
        await msg.edit(
            embed=tombola_global_embed(record),
            view=TombolaGlobalPaymentView(record["id"])
        )
    except Exception as exc:
        print(f"Erreur refresh total Tombola: {exc}")


async def refresh_all_tombola_vehicle_messages(record):
    for i in range(len(record.get("vehicles", []))):
        await refresh_tombola_vehicle_message(record, i)


class TombolaPricesModal(discord.ui.Modal, title="Modifier les prix Tombola"):
    price_v1 = discord.ui.TextInput(label="Prix Véhicule 1", placeholder="Vide = en attente", required=False, max_length=15)
    price_v2 = discord.ui.TextInput(label="Prix Véhicule 2", placeholder="Vide = en attente", required=False, max_length=15)

    def __init__(self, record_id, record):
        super().__init__()
        self.record_id=str(record_id)
        vehicles=record.get("vehicles",[])
        if len(vehicles)>0 and vehicles[0].get("price") is not None: self.price_v1.default=str(vehicles[0]["price"])
        if len(vehicles)>1 and vehicles[1].get("price") is not None: self.price_v2.default=str(vehicles[1]["price"])

    def parse_price(self,value):
        raw=str(value or "").strip()
        if not raw: return None
        price=int(raw.replace(" ","").replace(".","").replace(",",""))
        if price < 0: raise ValueError
        return price

    async def on_submit(self,interaction):
        try:
            prices=[self.parse_price(self.price_v1.value),self.parse_price(self.price_v2.value)]
        except ValueError:
            await interaction.response.send_message("❌ Prix invalide.",ephemeral=True); return
        data=load_tombola_data()
        record=data.setdefault("records",{}).get(self.record_id)
        if not record:
            await interaction.response.defer(); return
        for i,price in enumerate(prices):
            if i < len(record.get("vehicles",[])): record["vehicles"][i]["price"]=price
        save_tombola_data(data)
        await interaction.response.edit_message(embed=tombola_global_embed(record),view=TombolaGlobalPaymentView(self.record_id))


class TombolaGlobalPaymentView(discord.ui.View):
    def __init__(self, record_id):
        super().__init__(timeout=None)
        self.record_id = str(record_id)

        # Ligne 1 : achats individuels
        for index in range(2):
            button = discord.ui.Button(
                label=f"Acheté V{index + 1}",
                emoji="🛒",
                style=discord.ButtonStyle.secondary,
                custom_id=f"tombola_buy_v{index + 1}:{self.record_id}"[:100],
                row=0
            )
            button.callback = self._make_bought_callback(index)
            self.add_item(button)

        # Ligne 1 : paiements individuels
        for index in range(2):
            button = discord.ui.Button(
                label=f"Payé V{index + 1}",
                emoji="💳",
                style=discord.ButtonStyle.secondary,
                custom_id=f"tombola_pay_v{index + 1}:{self.record_id}"[:100],
                row=0
            )
            button.callback = self._make_paid_callback(index)
            self.add_item(button)

        # Ligne 2 : paiement global
        pay_all = discord.ui.Button(
            label="Tout payer",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id=f"tombola_pay_all:{self.record_id}"[:100],
            row=1
        )
        pay_all.callback = self.pay_all
        self.add_item(pay_all)

        reset_all = discord.ui.Button(
            label="Tout remettre en attente",
            emoji="↩️",
            style=discord.ButtonStyle.danger,
            custom_id=f"tombola_reset_all:{self.record_id}"[:100],
            row=1
        )
        reset_all.callback = self.reset_all
        self.add_item(reset_all)

        edit_prices = discord.ui.Button(label="Modifier prix", emoji="✏️", style=discord.ButtonStyle.primary,
                                        custom_id=f"tombola_edit_prices:{self.record_id}"[:100], row=1)
        edit_prices.callback = self.edit_prices
        self.add_item(edit_prices)

    async def interaction_check(self, interaction):
        if not tombola_allowed(interaction):
            await interaction.response.send_message(
                "❌ Tu n'as pas la permission.",
                ephemeral=True
            )
            return False
        return True

    def _make_bought_callback(self, index):
        async def callback(interaction):
            data = load_tombola_data()
            record = data.setdefault("records", {}).get(self.record_id)
            if not record or index >= len(record.get("vehicles", [])):
                await interaction.response.defer()
                return

            vehicle = record["vehicles"][index]
            vehicle["bought"] = not vehicle.get("bought", False)
            save_tombola_data(data)

            await interaction.response.edit_message(
                embed=tombola_global_embed(record),
                view=TombolaGlobalPaymentView(self.record_id)
            )
        return callback

    def _make_paid_callback(self, index):
        async def callback(interaction):
            data = load_tombola_data()
            record = data.setdefault("records", {}).get(self.record_id)
            if not record or index >= len(record.get("vehicles", [])):
                await interaction.response.defer()
                return

            vehicle = record["vehicles"][index]
            vehicle["paid"] = not vehicle.get("paid", False)
            save_tombola_data(data)

            await interaction.response.edit_message(
                embed=tombola_global_embed(record),
                view=TombolaGlobalPaymentView(self.record_id)
            )
        return callback

    async def edit_prices(self, interaction):
        data=load_tombola_data()
        record=data.setdefault("records",{}).get(self.record_id)
        if not record:
            await interaction.response.defer(); return
        await interaction.response.send_modal(TombolaPricesModal(self.record_id,record))

    async def pay_all(self, interaction):
        data = load_tombola_data()
        record = data.setdefault("records", {}).get(self.record_id)
        if not record:
            await interaction.response.defer()
            return

        for vehicle in record.get("vehicles", []):
            vehicle["paid"] = True

        save_tombola_data(data)
        await interaction.response.edit_message(
            embed=tombola_global_embed(record),
            view=TombolaGlobalPaymentView(self.record_id)
        )

    async def reset_all(self, interaction):
        data = load_tombola_data()
        record = data.setdefault("records", {}).get(self.record_id)
        if not record:
            await interaction.response.defer()
            return

        # Remet achat ET paiement en attente pour les deux véhicules.
        for vehicle in record.get("vehicles", []):
            vehicle["bought"] = False
            vehicle["paid"] = False

        save_tombola_data(data)
        await interaction.response.edit_message(
            embed=tombola_global_embed(record),
            view=TombolaGlobalPaymentView(self.record_id)
        )


class TombolaVehicleEditModal(discord.ui.Modal, title="Modifier le véhicule"):
    name_input = discord.ui.TextInput(label="Nom du véhicule", max_length=100)
    price_input = discord.ui.TextInput(label="Prix", max_length=15)

    def __init__(self, record_id, index, vehicle):
        super().__init__()
        self.record_id = str(record_id)
        self.index = int(index)
        self.name_input.default = vehicle.get("name", "")
        self.price_input.default = str(vehicle.get("price", 0))

    async def on_submit(self, interaction):
        try:
            price = int(str(self.price_input.value).replace(" ", "").replace(".", "").replace(",", ""))
            if price < 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ Prix invalide.", ephemeral=True)
            return

        data = load_tombola_data()
        record = data.setdefault("records", {}).get(self.record_id)
        if not record or self.index >= len(record.get("vehicles", [])):
            await interaction.response.send_message("❌ Véhicule introuvable.", ephemeral=True)
            return

        record["vehicles"][self.index]["name"] = str(self.name_input.value).strip()
        record["vehicles"][self.index]["price"] = price
        save_tombola_data(data)

        await interaction.response.send_message("✅ Véhicule modifié.", ephemeral=True)
        await refresh_tombola_vehicle_message(record, self.index)
        await refresh_tombola_global_message(record)


class TombolaVehicleStatusView(discord.ui.View):
    def __init__(self, record_id, index):
        super().__init__(timeout=None)
        self.record_id = str(record_id)
        self.index = int(index)

        bought = discord.ui.Button(
            label="Acheté",
            emoji="🟢",
            style=discord.ButtonStyle.success,
            custom_id=f"tombola_bought:{self.record_id}:{self.index}"[:100]
        )
        bought.callback = self.toggle_bought
        self.add_item(bought)

        paid = discord.ui.Button(
            label="Payé",
            emoji="🟢",
            style=discord.ButtonStyle.success,
            custom_id=f"tombola_paid:{self.record_id}:{self.index}"[:100]
        )
        paid.callback = self.toggle_paid
        self.add_item(paid)

        edit = discord.ui.Button(
            label="Modifier",
            emoji="✏️",
            style=discord.ButtonStyle.secondary,
            custom_id=f"tombola_edit:{self.record_id}:{self.index}"[:100]
        )
        edit.callback = self.edit_vehicle
        self.add_item(edit)

    def load_record(self):
        data = load_tombola_data()
        return data, data.setdefault("records", {}).get(self.record_id)

    async def interaction_check(self, interaction):
        if not tombola_allowed(interaction):
            await interaction.response.send_message("❌ Tu n'as pas la permission.", ephemeral=True)
            return False
        return True

    async def toggle_bought(self, interaction):
        data, record = self.load_record()
        if not record:
            await interaction.response.send_message("❌ Tombola introuvable.", ephemeral=True)
            return
        v = record["vehicles"][self.index]
        v["bought"] = not v.get("bought", False)
        save_tombola_data(data)
        await interaction.response.edit_message(
            embed=tombola_vehicle_embed(record, self.index),
            view=TombolaVehicleStatusView(self.record_id, self.index)
        )

    async def toggle_paid(self, interaction):
        data, record = self.load_record()
        if not record:
            await interaction.response.send_message("❌ Tombola introuvable.", ephemeral=True)
            return
        v = record["vehicles"][self.index]
        v["paid"] = not v.get("paid", False)
        save_tombola_data(data)
        await interaction.response.edit_message(
            embed=tombola_vehicle_embed(record, self.index),
            view=TombolaVehicleStatusView(self.record_id, self.index)
        )

        await refresh_tombola_global_message(record)

    async def edit_vehicle(self, interaction):
        data, record = self.load_record()
        if not record:
            await interaction.response.send_message("❌ Tombola introuvable.", ephemeral=True)
            return
        await interaction.response.send_modal(
            TombolaVehicleEditModal(self.record_id, self.index, record["vehicles"][self.index])
        )


class DraftPriceModal(discord.ui.Modal, title="Prix du véhicule"):
    price_input = discord.ui.TextInput(label="Prix (optionnel)", placeholder="Vide = en attente de prix", max_length=15, required=False)

    def __init__(self, uid, idx, vehicle_type, vehicle_name):
        super().__init__()
        self.uid=int(uid); self.idx=int(idx); self.vehicle_type=vehicle_type; self.vehicle_name=vehicle_name

    async def on_submit(self, interaction):
        raw_price=str(self.price_input.value or "").strip()
        price=None
        if raw_price:
            try:
                price=int(raw_price.replace(" ","").replace(".","").replace(",",""))
                if price < 0: raise ValueError
            except ValueError:
                await interaction.response.send_message("❌ Prix invalide.",ephemeral=True); return
        draft=TOMBOLA_DRAFTS.setdefault(self.uid,new_tombola_draft())
        while len(draft["vehicles"]) <= self.idx: draft["vehicles"].append(None)
        draft["vehicles"][self.idx]={"name":self.vehicle_name,"type":self.vehicle_type,"price":price,"bought":False,"paid":False}
        await interaction.response.edit_message(content=None,embed=tombola_draft_embed(draft),view=DraftView(self.uid))


class DraftNewModal(discord.ui.Modal, title="Nouveau véhicule"):
    name_input=discord.ui.TextInput(label="Nom du véhicule",max_length=100)
    price_input=discord.ui.TextInput(label="Prix (optionnel)",placeholder="Vide = en attente de prix",max_length=15,required=False)

    def __init__(self,uid,idx,vehicle_type):
        super().__init__()
        self.uid=int(uid); self.idx=int(idx); self.vehicle_type=vehicle_type

    async def on_submit(self,interaction):
        name=str(self.name_input.value).strip()
        raw_price=str(self.price_input.value or "").strip()
        price=None
        if raw_price:
            try:
                price=int(raw_price.replace(" ","").replace(".","").replace(",",""))
                if price < 0: raise ValueError
            except ValueError:
                await interaction.response.send_message("❌ Prix invalide.",ephemeral=True); return
        cat=load_vehicle_catalog()
        bucket="voitures" if self.vehicle_type=="voiture" else "motos"
        if not any(x.casefold()==name.casefold() for x in cat[bucket]):
            cat[bucket].append(name); save_vehicle_catalog(cat)
        draft=TOMBOLA_DRAFTS.setdefault(self.uid,new_tombola_draft())
        while len(draft["vehicles"]) <= self.idx: draft["vehicles"].append(None)
        draft["vehicles"][self.idx]={"name":name,"type":self.vehicle_type,"price":price,"bought":False,"paid":False}
        await interaction.response.edit_message(content=None,embed=tombola_draft_embed(draft),view=DraftView(self.uid))


async def return_to_tombola_draft(interaction, uid):
    """Retourne au formulaire principal sans effacer le brouillon."""
    draft = TOMBOLA_DRAFTS.get(int(uid))
    if not draft:
        draft = new_tombola_draft()
        TOMBOLA_DRAFTS[int(uid)] = draft

    await interaction.response.edit_message(
        content=None,
        embed=tombola_draft_embed(draft),
        view=DraftView(int(uid))
    )


class TombolaBackButton(discord.ui.Button):
    def __init__(self, uid, row=None):
        super().__init__(
            label="Retour",
            emoji="↩️",
            style=discord.ButtonStyle.secondary,
            row=row
        )
        self.uid = int(uid)

    async def callback(self, interaction):
        await return_to_tombola_draft(interaction, self.uid)


# ===== Correctif V5 : composants de préparation Tombola =====

class DraftWeekModal(discord.ui.Modal, title="Choisir la semaine"):
    date_input = discord.ui.TextInput(
        label="Une date de la semaine",
        placeholder="Ex : 14/09 ou 14/09/2027",
        max_length=10
    )

    def __init__(self, uid):
        super().__init__()
        self.uid = int(uid)

    async def on_submit(self, interaction):
        raw_date = str(self.date_input.value).strip()
        try:
            # JJ/MM = année en cours automatiquement.
            # JJ/MM/AAAA = année saisie manuellement.
            if len(raw_date.split("/")) == 2:
                current_year = datetime.now().year
                day = datetime.strptime(
                    f"{raw_date}/{current_year}",
                    "%d/%m/%Y"
                ).date()
            else:
                day = datetime.strptime(
                    raw_date,
                    "%d/%m/%Y"
                ).date()
        except ValueError:
            await interaction.response.send_message(
                "❌ Date invalide. Utilise **JJ/MM** ou **JJ/MM/AAAA**.",
                ephemeral=True
            )
            return

        _, monday, sunday = week_key_from_date(day)
        draft = TOMBOLA_DRAFTS.setdefault(self.uid, new_tombola_draft())
        draft["start"] = monday.isoformat()
        draft["end"] = sunday.isoformat()

        await interaction.response.edit_message(
            content=None,
            embed=tombola_draft_embed(draft),
            view=DraftView(self.uid)
        )


class DraftSearchModal(discord.ui.Modal, title="Rechercher le véhicule"):
    search_input = discord.ui.TextInput(
        label="Nom ou partie du nom",
        placeholder="Ex : sun → Sunrise",
        max_length=100
    )

    def __init__(self, uid, idx, vehicle_type):
        super().__init__()
        self.uid = int(uid)
        self.idx = int(idx)
        self.vehicle_type = vehicle_type

    async def on_submit(self, interaction):
        query = str(self.search_input.value).strip().casefold()
        catalog = load_vehicle_catalog()
        bucket = "voitures" if self.vehicle_type == "voiture" else "motos"
        names = catalog.get(bucket, [])

        starts = [x for x in names if x.casefold().startswith(query)]
        contains = [
            x for x in names
            if query in x.casefold() and not x.casefold().startswith(query)
        ]
        matches = (starts + contains)[:25]

        if not matches:
            await interaction.response.edit_message(
                content=(
                    f"❌ Aucun véhicule trouvé avec **{self.search_input.value}**.\n"
                    "Tu peux faire une nouvelle recherche ou ajouter le véhicule au catalogue."
                ),
                embed=None,
                view=DraftNoResultView(self.uid, self.idx, self.vehicle_type)
            )
            return

        await interaction.response.edit_message(
            content=(
                f"🔎 Résultats pour **{self.search_input.value}**\n"
                "Choisis le véhicule :"
            ),
            embed=None,
            view=DraftResultsView(
                self.uid,
                self.idx,
                self.vehicle_type,
                matches
            )
        )


class DraftResultSelect(discord.ui.Select):
    def __init__(self, uid, idx, vehicle_type, matches):
        self.uid = int(uid)
        self.idx = int(idx)
        self.vehicle_type = vehicle_type

        super().__init__(
            placeholder="Sélectionner le véhicule",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label=name[:100], value=name)
                for name in matches
            ]
        )

    async def callback(self, interaction):
        await interaction.response.send_modal(
            DraftPriceModal(
                self.uid,
                self.idx,
                self.vehicle_type,
                self.values[0]
            )
        )


class DraftResultsView(discord.ui.View):
    def __init__(self, uid, idx, vehicle_type, matches):
        super().__init__(timeout=300)
        self.uid = int(uid)
        self.idx = int(idx)
        self.vehicle_type = vehicle_type

        self.add_item(
            DraftResultSelect(uid, idx, vehicle_type, matches)
        )
        self.add_item(TombolaBackButton(uid))

        again = discord.ui.Button(
            label="Nouvelle recherche",
            emoji="🔎",
            style=discord.ButtonStyle.secondary
        )
        again.callback = self.search_again
        self.add_item(again)

    async def search_again(self, interaction):
        await interaction.response.send_modal(
            DraftSearchModal(
                self.uid,
                self.idx,
                self.vehicle_type
            )
        )


class DraftNoResultView(discord.ui.View):
    def __init__(self, uid, idx, vehicle_type):
        super().__init__(timeout=300)
        self.uid = int(uid)
        self.idx = int(idx)
        self.vehicle_type = vehicle_type
        self.add_item(TombolaBackButton(uid))

    @discord.ui.button(
        label="Rechercher à nouveau",
        emoji="🔎",
        style=discord.ButtonStyle.primary
    )
    async def again(self, interaction, button):
        await interaction.response.send_modal(
            DraftSearchModal(
                self.uid,
                self.idx,
                self.vehicle_type
            )
        )

    @discord.ui.button(
        label="Ajouter au catalogue",
        emoji="➕",
        style=discord.ButtonStyle.success
    )
    async def add(self, interaction, button):
        await interaction.response.send_modal(
            DraftNewModal(
                self.uid,
                self.idx,
                self.vehicle_type
            )
        )


class DraftSearchView(discord.ui.View):
    def __init__(self, uid, idx, vehicle_type):
        super().__init__(timeout=300)
        self.uid = int(uid)
        self.idx = int(idx)
        self.vehicle_type = vehicle_type
        self.add_item(TombolaBackButton(uid))

    @discord.ui.button(
        label="Rechercher le véhicule",
        emoji="🔎",
        style=discord.ButtonStyle.primary
    )
    async def search(self, interaction, button):
        await interaction.response.send_modal(
            DraftSearchModal(
                self.uid,
                self.idx,
                self.vehicle_type
            )
        )

    @discord.ui.button(
        label="Nouveau véhicule",
        emoji="➕",
        style=discord.ButtonStyle.success
    )
    async def new_vehicle(self, interaction, button):
        await interaction.response.send_modal(
            DraftNewModal(
                self.uid,
                self.idx,
                self.vehicle_type
            )
        )

    @discord.ui.button(
        label="Changer le type",
        emoji="🔁",
        style=discord.ButtonStyle.secondary
    )
    async def change_type(self, interaction, button):
        await interaction.response.edit_message(
            content=f"**Véhicule {self.idx + 1}** : choisis le type.",
            embed=None,
            view=TypeView(self.uid, self.idx)
        )


class DraftTypeSelect(discord.ui.Select):
    def __init__(self, uid, idx):
        self.uid = int(uid)
        self.idx = int(idx)

        super().__init__(
            placeholder="Type de véhicule",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label="Voiture",
                    value="voiture",
                    emoji="🚗"
                ),
                discord.SelectOption(
                    label="Moto",
                    value="moto",
                    emoji="🏍️"
                )
            ]
        )

    async def callback(self, interaction):
        vehicle_type = self.values[0]
        label = "Voiture" if vehicle_type == "voiture" else "Moto"
        emoji = "🚗" if vehicle_type == "voiture" else "🏍️"

        await interaction.response.edit_message(
            content=(
                f"{emoji} **{label}** sélectionnée.\n"
                "Clique sur **Rechercher le véhicule** puis écris une partie du nom.\n"
                "Exemple : `sun` → **Sunrise**."
            ),
            embed=None,
            view=DraftSearchView(
                self.uid,
                self.idx,
                vehicle_type
            )
        )


class TypeView(discord.ui.View):
    def __init__(self, uid, idx):
        super().__init__(timeout=300)
        self.add_item(DraftTypeSelect(uid, idx))
        self.add_item(TombolaBackButton(uid))


class DraftView(discord.ui.View):
    def __init__(self,uid): super().__init__(timeout=600); self.uid=uid
    async def interaction_check(self,it):
        if it.user.id!=self.uid: await it.response.send_message("❌ Ce formulaire n'est pas le tien.",ephemeral=True); return False
        return True
    @discord.ui.button(label="Véhicule 1",emoji="1️⃣",style=discord.ButtonStyle.primary)
    async def v1(self,it,b): await it.response.edit_message(content="**Véhicule 1** : choisis le type.",embed=None,view=TypeView(self.uid,0))
    @discord.ui.button(label="Véhicule 2",emoji="2️⃣",style=discord.ButtonStyle.primary)
    async def v2(self,it,b): await it.response.edit_message(content="**Véhicule 2** : choisis le type.",embed=None,view=TypeView(self.uid,1))
    @discord.ui.button(label="Ajouter véhicule",emoji="➕",style=discord.ButtonStyle.secondary)
    async def extra(self,it,b):
        dr=TOMBOLA_DRAFTS[self.uid]; dr["vehicles"].append(None); idx=len(dr["vehicles"])-1
        await it.response.edit_message(content=f"**Véhicule {idx+1}** : choisis le type.",embed=None,view=TypeView(self.uid,idx))
    @discord.ui.button(label="Semaine",emoji="📅",style=discord.ButtonStyle.secondary)
    async def week(self,it,b): await it.response.send_modal(DraftWeekModal(self.uid))
    @discord.ui.button(label="Valider",emoji="✅",style=discord.ButtonStyle.success)
    async def valid(self,it,b):
        dr=TOMBOLA_DRAFTS.get(self.uid)
        if not dr or not dr["vehicles"][0] or not dr["vehicles"][1]:
            await it.response.send_message("❌ Configure **Véhicule 1** et **Véhicule 2**.",ephemeral=True)
            return

        vehicles=[x for x in dr["vehicles"] if x]
        data=load_tombola_data()
        records=data.setdefault("records",{})
        rid=f"{dr['start']}:{it.id}"
        record={
            "id":rid,
            "start":dr["start"],
            "end":dr["end"],
            "vehicles":vehicles,
            "channel_id":TOMBOLA_CHANNEL_ID,
            "message_ids":[]
        }

        channel=bot.get_channel(TOMBOLA_CHANNEL_ID) or await bot.fetch_channel(TOMBOLA_CHANNEL_ID)
        if not isinstance(channel, discord.abc.Messageable):
            raise ValueError("Le salon Discord configuré ne permet pas les messages.")

        # Une seule fiche Discord pour toute la Tombola.
        # Aucun message individuel V1 / V2.

        # Message global de la semaine : véhicules + achats + paiements + total.
        global_msg = await channel.send(
            embed=tombola_global_embed(record),
            view=TombolaGlobalPaymentView(rid)
        )
        record["global_message_id"] = str(global_msg.id)

        records[rid]=record
        save_tombola_data(data)
        TOMBOLA_DRAFTS.pop(self.uid,None)
        # Une fois publié, on retire simplement le formulaire privé.
        # Aucun message "bien publié" ou confirmation inutile.
        await it.response.defer()
        try:
            await it.delete_original_response()
        except Exception:
            pass


# =========================
# TOMBOLA : PERSISTANCE DES ANCIENS MESSAGES
# =========================

def _tombola_message_component_ids(message):
    """Retourne les custom_id présents sur un message Discord."""
    ids = []
    for action_row in getattr(message, "components", []) or []:
        for component in getattr(action_row, "children", []) or []:
            cid = getattr(component, "custom_id", None)
            if cid:
                ids.append(str(cid))
    return ids


def _tombola_rid_from_component_ids(component_ids):
    """Extrait l'identifiant d'une Tombola depuis ses boutons actuels.
    Les très anciennes fiches `tombola:record:v1/v2` n'embarquent pas l'ID :
    elles sont associées par leur message_id pendant le scan d'historique.
    """
    global_prefixes = (
        "tombola_buy_v1:", "tombola_buy_v2:",
        "tombola_pay_v1:", "tombola_pay_v2:",
        "tombola_pay_all:", "tombola_unpay_all:",
        "tombola_reset_all:", "tombola_edit_prices:",
    )
    vehicle_prefixes = ("tombola_bought:", "tombola_paid:", "tombola_edit:")

    for cid in component_ids:
        for prefix in global_prefixes:
            if cid.startswith(prefix):
                return cid[len(prefix):]
        for prefix in vehicle_prefixes:
            if cid.startswith(prefix):
                payload = cid[len(prefix):]
                # Le record_id contient lui-même ':' ; seul le dernier ':' sépare l'index.
                if ":" in payload:
                    rid, _index = payload.rsplit(":", 1)
                    return rid
    return None


def _tombola_is_very_legacy_record(component_ids):
    """Anciennes fiches publiées avec les boutons fixes Véhicule 1 / Véhicule 2."""
    ids = set(component_ids or [])
    return bool(ids.intersection({"tombola:record:v1", "tombola:record:v2"}))


def _tombola_find_record_by_message_id(records, message_id):
    """Retrouve une ancienne fiche grâce à son ID Discord, même avec l'ancien schéma JSON."""
    wanted = str(message_id)
    for rid, record in records.items():
        if not isinstance(record, dict):
            continue
        candidates = (
            record.get("global_message_id"),
            record.get("message_id"),  # ancien format
        )
        if any(str(value) == wanted for value in candidates if value):
            return str(record.get("id") or rid), record
    return None, None


def _tombola_vehicle_index_from_component_ids(component_ids):
    for cid in component_ids:
        for prefix in ("tombola_bought:", "tombola_paid:", "tombola_edit:"):
            if cid.startswith(prefix):
                payload = cid[len(prefix):]
                if ":" in payload:
                    _rid, index = payload.rsplit(":", 1)
                    try:
                        return int(index)
                    except ValueError:
                        return None
    return None


def _tombola_dates_from_record_id(record_id):
    """Les IDs créés par le bot commencent par YYYY-MM-DD."""
    try:
        start = datetime.fromisoformat(str(record_id).split(":", 1)[0]).date()
    except (TypeError, ValueError):
        _, start, _ = week_key_from_date(datetime.now(TIMEZONE).date())
    end = start + timedelta(days=6)
    return start.isoformat(), end.isoformat()


def _tombola_money_from_text(value):
    value = str(value or "")
    if "ATTENTE DE PRIX" in value.upper():
        return None
    digits = re.sub(r"[^0-9]", "", value)
    return int(digits) if digits else None


def _tombola_blank_vehicle():
    return {
        "name": "Inconnu",
        "type": "voiture",
        "price": None,
        "bought": False,
        "paid": False,
    }


def _tombola_parse_global_embed(message, record_id):
    """Reconstruit au mieux une fiche globale si son JSON local a disparu."""
    if not getattr(message, "embeds", None):
        return []
    description = message.embeds[0].description or ""
    vehicles = []

    # Compatible V9, V10 et versions suivantes.
    pattern = re.compile(
        r"(?P<icon>🚗|🏍️)\s*\*\*Véhicule\s*(?P<index>\d+)\s*:\s*(?P<name>.*?)\*\*\s*•\s*(?P<rest>.*)",
        re.IGNORECASE,
    )
    for raw_line in description.splitlines():
        match = pattern.search(raw_line.strip())
        if not match:
            continue
        idx = max(0, int(match.group("index")) - 1)
        while len(vehicles) <= idx:
            vehicles.append(_tombola_blank_vehicle())
        rest = match.group("rest")
        parts = rest.split("•")
        first_part = parts[0]
        status_upper = " • ".join(parts[1:]).upper() if len(parts) > 1 else ""
        vehicles[idx] = {
            "name": match.group("name").strip() or "Inconnu",
            "type": "voiture" if match.group("icon") == "🚗" else "moto",
            "price": _tombola_money_from_text(first_part),
            "bought": ("ACHETÉ" in status_upper and "À ACHETER" not in status_upper),
            "paid": ("PAYÉ" in status_upper and "EN ATTENTE" not in status_upper),
        }
    return vehicles


def _tombola_parse_vehicle_embed(message, index):
    """Reconstruit une ancienne fiche individuelle V8/V9."""
    if not getattr(message, "embeds", None):
        return None
    embed = message.embeds[0]
    description = embed.description or ""
    icon = "🏍️" if "🏍️" in description or "🏍️" in (embed.title or "") else "🚗"

    name = "Inconnu"
    for line in description.splitlines():
        stripped = line.strip()
        if ("🚗" in stripped or "🏍️" in stripped) and "**" in stripped:
            match = re.search(r"(?:🚗|🏍️)\s*\*\*(.+?)\*\*", stripped)
            if match:
                name = match.group(1).strip()
                break

    price = None
    match = re.search(r"Prix\s*:\s*\*\*(.*?)\*\*", description, re.IGNORECASE)
    if match:
        price = _tombola_money_from_text(match.group(1))

    bought = False
    paid = False
    for field in getattr(embed, "fields", []) or []:
        fname = (field.name or "").upper()
        fvalue = (field.value or "").upper()
        if "ACHAT" in fname:
            bought = "ACHETÉ" in fvalue and "À ACHETER" not in fvalue
        elif "PAIEMENT" in fname:
            paid = "PAYÉ" in fvalue and "EN ATTENTE" not in fvalue

    return {
        "name": name,
        "type": "voiture" if icon == "🚗" else "moto",
        "price": price,
        "bought": bought,
        "paid": paid,
    }



def _tombola_parse_very_legacy_record(message):
    """Reconstruit les fiches de l'ancienne version `RecordView`.

    Ancien rendu :
      titre : 🎟️ Véhicules Tombola
      description : 📅 Semaine du JJ/MM/AAAA au JJ/MM/AAAA
      champs : 🚗 Véhicule 1 / 🏍️ Véhicule 2
               **Nom**
               💰 **300 000 $**
               🛒 🟢 Acheté / 🟠 À acheter
               💳 🟢 Payé / 🔴 En attente de paiement
    """
    if not getattr(message, "embeds", None):
        return None

    embed = message.embeds[0]
    description = embed.description or ""
    start = end = None

    m = re.search(
        r"Semaine\s+du\s+(\d{1,2}/\d{1,2}/\d{4})\s+au\s+(\d{1,2}/\d{1,2}/\d{4})",
        description,
        re.IGNORECASE,
    )
    if m:
        try:
            start = datetime.strptime(m.group(1), "%d/%m/%Y").date().isoformat()
            end = datetime.strptime(m.group(2), "%d/%m/%Y").date().isoformat()
        except ValueError:
            start = end = None

    vehicles = []
    for field in getattr(embed, "fields", []) or []:
        field_name = str(field.name or "")
        number = re.search(r"Véhicule\s*(\d+)", field_name, re.IGNORECASE)
        if not number:
            continue

        idx = max(0, int(number.group(1)) - 1)
        while len(vehicles) <= idx:
            vehicles.append(_tombola_blank_vehicle())

        value = str(field.value or "")
        name_match = re.search(r"\*\*(.+?)\*\*", value)
        vehicle_name = name_match.group(1).strip() if name_match else "Inconnu"

        price = None
        price_match = re.search(r"(?:💰|💵)\s*\*\*(.*?)\*\*", value)
        if price_match:
            price = _tombola_money_from_text(price_match.group(1))

        upper = value.upper()
        bought = ("ACHETÉ" in upper and "À ACHETER" not in upper)
        paid = ("PAYÉ" in upper and "EN ATTENTE" not in upper)
        vehicle_type = "moto" if "🏍️" in field_name else "voiture"

        vehicles[idx] = {
            "name": vehicle_name,
            "type": vehicle_type,
            "price": price,
            "bought": bought,
            "paid": paid,
        }

    if not vehicles:
        return None

    if not start or not end:
        _, monday, sunday = week_key_from_date(message.created_at.astimezone(TIMEZONE).date())
        start, end = monday.isoformat(), sunday.isoformat()

    return {
        "start": start,
        "end": end,
        "vehicles": vehicles,
    }


async def _upgrade_very_legacy_tombola_message(record_id, record, message_id):
    """Après la première action sur une très ancienne fiche, la passe au format actuel."""
    channel_id = int(record.get("channel_id") or TOMBOLA_CHANNEL_ID)
    try:
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            raise ValueError("Le salon Discord configuré ne permet pas les messages.")
        message = await channel.fetch_message(int(message_id))
        await message.edit(
            embed=tombola_global_embed(record),
            view=TombolaGlobalPaymentView(str(record_id)),
        )
        data = load_tombola_data()
        saved = data.setdefault("records", {}).get(str(record_id))
        if isinstance(saved, dict):
            saved["global_message_id"] = str(message_id)
            saved.setdefault("message_id", str(message_id))
            save_tombola_data(data)
        # La vue courante est enregistrée immédiatement pour le reste de la session.
        bot.add_view(TombolaGlobalPaymentView(str(record_id)), message_id=int(message_id))
        return True
    except Exception as exc:
        print(f"[TOMBOLA] Migration ancienne fiche {message_id} impossible : {exc}")
        return False


class TombolaVeryLegacyActions(discord.ui.View):
    """Actions affichées après clic sur Véhicule 1/2 d'une ancienne fiche."""
    def __init__(self, record_id, index, public_message_id):
        super().__init__(timeout=180)
        self.record_id = str(record_id)
        self.index = int(index)
        self.public_message_id = int(public_message_id)

    async def interaction_check(self, interaction):
        if not tombola_allowed(interaction):
            await interaction.response.send_message("❌ Tu n'as pas la permission.", ephemeral=True)
            return False
        return True

    def _load(self):
        data = load_tombola_data()
        record = data.setdefault("records", {}).get(self.record_id)
        return data, record

    @discord.ui.button(label="Achat", emoji="🛒", style=discord.ButtonStyle.secondary)
    async def toggle_buy(self, interaction, button):
        data, record = self._load()
        if not record or self.index >= len(record.get("vehicles", [])):
            await interaction.response.send_message("❌ Véhicule introuvable.", ephemeral=True)
            return
        vehicle = record["vehicles"][self.index]
        vehicle["bought"] = not vehicle.get("bought", False)
        save_tombola_data(data)
        await interaction.response.send_message("✅ Statut achat modifié. L'ancienne fiche a été mise à jour.", ephemeral=True)
        await _upgrade_very_legacy_tombola_message(self.record_id, record, self.public_message_id)

    @discord.ui.button(label="Paiement", emoji="💳", style=discord.ButtonStyle.secondary)
    async def toggle_pay(self, interaction, button):
        data, record = self._load()
        if not record or self.index >= len(record.get("vehicles", [])):
            await interaction.response.send_message("❌ Véhicule introuvable.", ephemeral=True)
            return
        vehicle = record["vehicles"][self.index]
        vehicle["paid"] = not vehicle.get("paid", False)
        save_tombola_data(data)
        await interaction.response.send_message("✅ Statut paiement modifié. L'ancienne fiche a été mise à jour.", ephemeral=True)
        await _upgrade_very_legacy_tombola_message(self.record_id, record, self.public_message_id)

    @discord.ui.button(label="Modifier", emoji="✏️", style=discord.ButtonStyle.primary)
    async def edit_vehicle(self, interaction, button):
        data, record = self._load()
        if not record or self.index >= len(record.get("vehicles", [])):
            await interaction.response.send_message("❌ Véhicule introuvable.", ephemeral=True)
            return
        # Le modal actuel actualise ensuite les messages enregistrés.
        record["global_message_id"] = str(self.public_message_id)
        save_tombola_data(data)
        await interaction.response.send_modal(
            TombolaVehicleEditModal(self.record_id, self.index, record["vehicles"][self.index])
        )


class TombolaVeryLegacyRecordView(discord.ui.View):
    """Réactive les fiches créées avant le passage aux nouveaux custom_id Tombola."""
    def __init__(self, record_id):
        super().__init__(timeout=None)
        self.record_id = str(record_id)

        v1 = discord.ui.Button(
            label="Véhicule 1",
            emoji="1️⃣",
            style=discord.ButtonStyle.secondary,
            custom_id="tombola:record:v1",
        )
        v1.callback = self._callback(0)
        self.add_item(v1)

        v2 = discord.ui.Button(
            label="Véhicule 2",
            emoji="2️⃣",
            style=discord.ButtonStyle.secondary,
            custom_id="tombola:record:v2",
        )
        v2.callback = self._callback(1)
        self.add_item(v2)

    async def interaction_check(self, interaction):
        if not tombola_allowed(interaction):
            await interaction.response.send_message("❌ Tu n'as pas la permission.", ephemeral=True)
            return False
        return True

    def _callback(self, index):
        async def callback(interaction):
            data = load_tombola_data()
            record = data.setdefault("records", {}).get(self.record_id)
            if not record or index >= len(record.get("vehicles", [])):
                await interaction.response.send_message("❌ Véhicule introuvable.", ephemeral=True)
                return
            vehicle = record["vehicles"][index]
            await interaction.response.send_message(
                f"Gestion : **{vehicle.get('name', 'Véhicule')}**",
                view=TombolaVeryLegacyActions(self.record_id, index, interaction.message.id),
                ephemeral=True,
            )
        return callback


class TombolaLegacyUnpayView(discord.ui.View):
    """Compatibilité avec le bouton V9 `tombola_unpay_all:*`."""
    def __init__(self, record_id):
        super().__init__(timeout=None)
        self.record_id = str(record_id)
        button = discord.ui.Button(
            label="Tout remettre en attente",
            emoji="↩️",
            style=discord.ButtonStyle.secondary,
            custom_id=f"tombola_unpay_all:{self.record_id}"[:100],
        )
        button.callback = self.unpay_all
        self.add_item(button)

    async def interaction_check(self, interaction):
        if not tombola_allowed(interaction):
            await interaction.response.send_message("❌ Tu n'as pas la permission.", ephemeral=True)
            return False
        return True

    async def unpay_all(self, interaction):
        data = load_tombola_data()
        record = data.setdefault("records", {}).get(self.record_id)
        if not record:
            await interaction.response.send_message("❌ Tombola introuvable.", ephemeral=True)
            return
        for vehicle in record.get("vehicles", []):
            if isinstance(vehicle, dict):
                vehicle["paid"] = False
        save_tombola_data(data)
        # Au premier clic, l'ancienne fiche est mise au format actuel.
        await interaction.response.edit_message(
            embed=tombola_global_embed(record),
            view=TombolaGlobalPaymentView(self.record_id),
        )
        await refresh_all_tombola_vehicle_messages(record)


def register_saved_tombola_views():
    """
    Réenregistre sans appel HTTP toutes les vues connues dans tombola_vehicules.json.
    Cela couvre aussi les fiches individuelles des anciennes versions V8/V9.
    """
    data = load_tombola_data()
    records = data.setdefault("records", {})
    global_count = 0
    vehicle_count = 0
    for record_id, record in records.items():
        if not isinstance(record, dict):
            continue
        record_id = str(record.get("id") or record_id)

        global_mid = record.get("global_message_id")
        legacy_mid = record.get("message_id")  # très ancien format RecordView

        if global_mid:
            try:
                mid = int(global_mid)
                bot.add_view(TombolaGlobalPaymentView(record_id), message_id=mid)
                # Bouton présent uniquement dans l'ancien résumé V9.
                bot.add_view(TombolaLegacyUnpayView(record_id), message_id=mid)
                global_count += 1
            except (TypeError, ValueError):
                print(f"[TOMBOLA] global_message_id invalide pour {record_id}: {global_mid}")

        # Anciennes fiches avec boutons fixes `tombola:record:v1/v2`.
        # On les enregistre par message_id, ce qui permet d'avoir le même custom_id
        # sur plusieurs anciens messages sans mélange entre les semaines.
        if legacy_mid and str(legacy_mid) != str(global_mid or ""):
            try:
                bot.add_view(TombolaVeryLegacyRecordView(record_id), message_id=int(legacy_mid))
                global_count += 1
            except (TypeError, ValueError):
                print(f"[TOMBOLA] ancien message_id invalide pour {record_id}: {legacy_mid}")

        for index, message_id in enumerate(record.get("message_ids", []) or []):
            if not message_id:
                continue
            try:
                bot.add_view(TombolaVehicleStatusView(record_id, index), message_id=int(message_id))
                vehicle_count += 1
            except (TypeError, ValueError):
                print(f"[TOMBOLA] message_id véhicule invalide pour {record_id}: {message_id}")

    print(
        f"[TOMBOLA] Vues locales restaurées : {global_count} fiche(s) globale(s), "
        f"{vehicle_count} ancienne(s) fiche(s) véhicule."
    )



async def restore_tombola_legacy_panels_after_restart():
    """Réactive les panneaux Tombola des toutes premières versions sans les modifier."""
    await bot.wait_until_ready()
    restored = 0
    try:
        channel = bot.get_channel(TOMBOLA_PANEL_CHANNEL_ID) or await bot.fetch_channel(TOMBOLA_PANEL_CHANNEL_ID)
        if not isinstance(channel, discord.abc.Messageable):
            raise ValueError("Le salon Discord configuré ne permet pas les messages.")
        async for message in channel.history(limit=None, oldest_first=False):
            if not bot.user or message.author.id != bot.user.id:
                continue
            ids = set(_tombola_message_component_ids(message))
            if "tombola:start" in ids:
                bot.add_view(TombolaPanel(), message_id=message.id)
                restored += 1
            elif ids.intersection({"tombola:vehicle1", "tombola:vehicle2", "tombola:extra", "tombola:week"}):
                bot.add_view(TombolaLegacyPanelView(), message_id=message.id)
                restored += 1
        if restored:
            print(f"[TOMBOLA] {restored} ancien(s) panneau(x) de gestion réactivé(s).")
    except Exception as exc:
        print(f"[TOMBOLA] Restauration des anciens panneaux impossible : {exc}")


async def restore_tombola_views_after_restart():
    """
    Parcourt l'historique du salon Tombola à chaque redémarrage.

    - réactive les boutons des messages créés avant la mise à jour ;
    - récupère leurs IDs de message dans le JSON s'ils manquent ;
    - reconstruit au mieux une ancienne fiche si son entrée JSON a été perdue ;
    - ne modifie aucun message Discord pendant le scan (pas de PATCH / pas de 429).
    """
    await bot.wait_until_ready()
    restored_global = 0
    restored_vehicle = 0
    adopted = 0
    reconstructed = 0
    changed = False

    try:
        channel = bot.get_channel(TOMBOLA_CHANNEL_ID) or await bot.fetch_channel(TOMBOLA_CHANNEL_ID)
        if not isinstance(channel, discord.abc.Messageable):
            raise ValueError("Le salon Discord configuré ne permet pas les messages.")
        data = load_tombola_data()
        records = data.setdefault("records", {})

        async for message in channel.history(limit=None, oldest_first=True):
            if not bot.user or message.author.id != bot.user.id:
                continue
            component_ids = _tombola_message_component_ids(message)
            if not component_ids or component_ids == ["tombola:start"]:
                continue

            very_legacy = _tombola_is_very_legacy_record(component_ids)
            record_id = _tombola_rid_from_component_ids(component_ids)

            # Les anciennes fiches RecordView avaient des custom_id fixes sans record_id.
            # On les rattache d'abord grâce au message_id sauvegardé. Si le JSON a été
            # perdu, on reconstruit la fiche directement depuis l'embed Discord.
            if very_legacy:
                found_id, found_record = _tombola_find_record_by_message_id(records, message.id)
                if found_record is not None:
                    record_id, record = found_id, found_record
                else:
                    parsed_legacy = _tombola_parse_very_legacy_record(message)
                    if not parsed_legacy:
                        continue
                    record_id = f"legacy:{message.id}"
                    record = {
                        "id": record_id,
                        "start": parsed_legacy["start"],
                        "end": parsed_legacy["end"],
                        "vehicles": parsed_legacy["vehicles"],
                        "channel_id": TOMBOLA_CHANNEL_ID,
                        "message_id": str(message.id),
                        "message_ids": [],
                    }
                    records[record_id] = record
                    reconstructed += 1
                    changed = True

                record.setdefault("id", record_id)
                record.setdefault("channel_id", TOMBOLA_CHANNEL_ID)
                record["message_id"] = str(message.id)
                bot.add_view(TombolaVeryLegacyRecordView(record_id), message_id=message.id)
                restored_global += 1
                adopted += 1
                changed = True
                continue

            if not record_id:
                continue

            record = records.get(record_id)
            if not isinstance(record, dict):
                start, end = _tombola_dates_from_record_id(record_id)
                record = {
                    "id": record_id,
                    "start": start,
                    "end": end,
                    "vehicles": [],
                    "channel_id": TOMBOLA_CHANNEL_ID,
                    "message_ids": [],
                }
                records[record_id] = record
                reconstructed += 1
                changed = True

            record.setdefault("id", record_id)
            record.setdefault("channel_id", TOMBOLA_CHANNEL_ID)
            record.setdefault("message_ids", [])
            if not record.get("start") or not record.get("end"):
                start, end = _tombola_dates_from_record_id(record_id)
                record["start"], record["end"] = start, end
                changed = True

            is_vehicle = any(
                cid.startswith(("tombola_bought:", "tombola_paid:", "tombola_edit:"))
                for cid in component_ids
            )
            is_global = any(
                cid.startswith((
                    "tombola_buy_v1:", "tombola_buy_v2:",
                    "tombola_pay_v1:", "tombola_pay_v2:",
                    "tombola_pay_all:", "tombola_unpay_all:",
                    "tombola_reset_all:", "tombola_edit_prices:",
                ))
                for cid in component_ids
            )

            if is_global:
                if str(record.get("global_message_id") or "") != str(message.id):
                    record["global_message_id"] = str(message.id)
                    adopted += 1
                    changed = True

                parsed = _tombola_parse_global_embed(message, record_id)
                if parsed and not record.get("vehicles"):
                    record["vehicles"] = parsed
                    changed = True

                bot.add_view(TombolaGlobalPaymentView(record_id), message_id=message.id)
                # Permet aussi aux anciennes fiches V9 de répondre à "Tout remettre en attente".
                bot.add_view(TombolaLegacyUnpayView(record_id), message_id=message.id)
                restored_global += 1

            if is_vehicle:
                index = _tombola_vehicle_index_from_component_ids(component_ids)
                if index is None or index < 0:
                    continue

                mids = record.setdefault("message_ids", [])
                while len(mids) <= index:
                    mids.append(None)
                if str(mids[index] or "") != str(message.id):
                    mids[index] = str(message.id)
                    adopted += 1
                    changed = True

                vehicles = record.setdefault("vehicles", [])
                while len(vehicles) <= index:
                    vehicles.append(_tombola_blank_vehicle())
                parsed_vehicle = _tombola_parse_vehicle_embed(message, index)
                if parsed_vehicle and (
                    not isinstance(vehicles[index], dict)
                    or vehicles[index].get("name") in (None, "", "Inconnu")
                ):
                    vehicles[index] = parsed_vehicle
                    changed = True

                bot.add_view(TombolaVehicleStatusView(record_id, index), message_id=message.id)
                restored_vehicle += 1

        if changed:
            save_tombola_data(data)

        print(
            f"[TOMBOLA] Restart : {restored_global} fiche(s) globale(s) et "
            f"{restored_vehicle} ancienne(s) fiche(s) véhicule réactivée(s). "
            f"{adopted} association(s) de message récupérée(s), "
            f"{reconstructed} fiche(s) reconstruite(s), anciennes versions incluses."
        )
    except Exception as exc:
        print(f"[TOMBOLA] Restauration de l'historique impossible : {exc}")
        print("[TOMBOLA] Vérifie l'accès à l'historique du salon Tombola et les permissions du bot.")



class TombolaLegacyPanelView(discord.ui.View):
    """Compatibilité avec le tout premier panneau Tombola (4 boutons fixes)."""
    def __init__(self):
        super().__init__(timeout=None)
        for label, emoji, cid, style in (
            ("Véhicule 1", "1️⃣", "tombola:vehicle1", discord.ButtonStyle.primary),
            ("Véhicule 2", "2️⃣", "tombola:vehicle2", discord.ButtonStyle.primary),
            ("Ajouter véhicule", "➕", "tombola:extra", discord.ButtonStyle.success),
            ("Changer semaine", "📅", "tombola:week", discord.ButtonStyle.secondary),
        ):
            button = discord.ui.Button(label=label, emoji=emoji, style=style, custom_id=cid)
            button.callback = self.redirect
            self.add_item(button)

    async def redirect(self, interaction: discord.Interaction):
        if not tombola_allowed(interaction):
            await interaction.response.send_message("❌ Permission refusée.", ephemeral=True)
            return
        TOMBOLA_DRAFTS[interaction.user.id] = new_tombola_draft()
        await interaction.response.send_message(
            "ℹ️ Cet ancien panneau a été repris par le nouveau système Tombola.",
            embed=tombola_draft_embed(TOMBOLA_DRAFTS[interaction.user.id]),
            view=DraftView(interaction.user.id),
            ephemeral=True,
        )


class TombolaPanel(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Ajouter véhicule",emoji="➕",style=discord.ButtonStyle.success,custom_id="tombola:start")
    async def start(self,it,b):
        if not tombola_allowed(it): await it.response.send_message("❌ Permission refusée.",ephemeral=True); return
        TOMBOLA_DRAFTS[it.user.id]=new_tombola_draft()
        await it.response.send_message(embed=tombola_draft_embed(TOMBOLA_DRAFTS[it.user.id]),view=DraftView(it.user.id),ephemeral=True)


@bot.tree.command(name="installer_sales", description="Installe uniquement le panneau Sales")
@discord.app_commands.guilds(discord.Object(id=GUILD_ID))
@discord.app_commands.describe(salon="Salon du panneau (salon actuel s'il est autorisé, sinon salon Sales principal)")
async def installer_sales(interaction: discord.Interaction, salon: discord.TextChannel | None = None):
    await interaction.response.defer(ephemeral=True)
    try:
        channel_id = salon.id if salon is not None else (
            interaction.channel_id if interaction.channel_id in SALES_CHANNEL_IDS else SALES_CHANNEL_ID
        )
        if channel_id not in SALES_CHANNEL_IDS:
            raise ValueError("Choisis le salon Sales principal ou le salon 1563696678081404989.")
        channel = await bot.fetch_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            raise ValueError("Le salon Discord configuré ne permet pas les messages.")
        embed = discord.Embed(title="📋 Gestion du sale", description="Clique sur le bouton ci-dessous pour enregistrer du sale.")
        await channel.send(embed=embed, view=SalesPanel())
        await interaction.followup.send(f"✅ Panneau Sales installé dans <#{channel_id}>.", ephemeral=True)
    except Exception as exc:
        await interaction.followup.send(f"❌ Installation impossible : `{exc}`", ephemeral=True)

@bot.tree.command(name="installer_machines", description="Installe uniquement le panneau Machines")
@discord.app_commands.guilds(discord.Object(id=GUILD_ID))
async def installer_machines(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        channel = await bot.fetch_channel(MACHINES_CHANNEL_ID)
        if not isinstance(channel, discord.abc.Messageable):
            raise ValueError("Le salon Discord configuré ne permet pas les messages.")
        embed = discord.Embed(title="💰 Gestion des Machines", description="Clique sur **Machine lancée** pour enregistrer un blanchiment.\nMontant vide : **1 000 000 $**\nMaximum : **1 000 000 $**\nRappel automatique : **4 h 45 après le lancement**.")
        await channel.send(embed=embed, view=MachinesPanel())
        await interaction.followup.send("✅ Panneau Machines installé.", ephemeral=True)
    except Exception as exc:
        await interaction.followup.send(f"❌ Installation impossible : `{exc}`", ephemeral=True)

@bot.tree.command(name="installer_tombola", description="Installe uniquement le panneau Véhicules Tombola")
@discord.app_commands.guilds(discord.Object(id=GUILD_ID))
async def installer_tombola(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if not tombola_allowed(interaction):
        await interaction.followup.send("❌ Tu n'as pas la permission.", ephemeral=True); return
    try:
        channel = await bot.fetch_channel(TOMBOLA_PANEL_CHANNEL_ID)
        if not isinstance(channel, discord.abc.Messageable):
            raise ValueError("Le salon Discord configuré ne permet pas les messages.")
        embed = discord.Embed(
            title="🎟️ Gestion des véhicules Tombola",
            description="Clique sur **Ajouter véhicule** pour préparer les véhicules de la semaine."
        )
        await channel.send(embed=embed, view=TombolaPanel())
        await interaction.followup.send("✅ Panneau Tombola installé.", ephemeral=True)
    except Exception as exc:
        await interaction.followup.send(f"❌ Installation impossible : `{exc}`", ephemeral=True)

@bot.tree.command(name="installer_panneaux", description="Ancienne commande : installe Sales et Machines")
@discord.app_commands.guilds(discord.Object(id=GUILD_ID))
async def installer_panneaux(interaction: discord.Interaction):
    await interaction.response.send_message(
        "ℹ️ Utilise maintenant `/installer_sales`, `/installer_machines` ou `/installer_tombola` pour installer chaque panneau séparément.",
        ephemeral=True
    )


def restore_machine_views_and_reminders():
    """Restaure boutons persistants et timers Machines après un redémarrage."""
    reminders = load_reminders()
    restored_views = 0
    restored_timers = 0

    for reminder in reminders:
        reminder_id = str(reminder.get("id") or "").strip()
        if not reminder_id:
            continue

        if reminder.get("cancelled", False):
            bot.add_view(MachineRelaunchView(reminder_id))
            restored_views += 1
        else:
            bot.add_view(MachineRecoveredView(
                reminder_id,
                recovered=bool(reminder.get("recovered", False))
            ))
            restored_views += 1

        sheet_row = reminder.get("sheet_row")
        if not reminder.get("cancelled", False):
            try:
                bot.add_view(MachineLaunchView(reminder_id, sheet_row))
                restored_views += 1
            except (TypeError, ValueError):
                print(f"[MACHINES] Ligne Sheet invalide pour {reminder_id}: {sheet_row}")

        if (
            not reminder.get("recovered", False)
            and not reminder.get("finished_notified", False)
            and not reminder.get("suppress_auto_reminders", False)
        ):
            schedule_reminder(reminder)
            restored_timers += 1

    print(f"[MACHINES] Restart : {restored_views} vue(s) restaurée(s), {restored_timers} timer(s) restauré(s).")



# =========================
# MACHINES : RESTAURATION DE L'HISTORIQUE DISCORD
# =========================

def _machine_message_component_ids(message):
    ids = []
    for row in getattr(message, "components", []) or []:
        for component in getattr(row, "children", []) or []:
            cid = getattr(component, "custom_id", None)
            if cid:
                ids.append(str(cid))
    return ids


def _machine_id_from_component_ids(component_ids):
    prefixes = (
        "machine_launch_again:", "machine_edit_time:", "machine_cancel:",
        "machine_recovered:", "machine_recovered_launch:",
        "machine_relaunch_cancelled:",
    )
    for cid in component_ids:
        for prefix in prefixes:
            if cid.startswith(prefix):
                return cid[len(prefix):]
    return None


def _machine_embed_field(message, contains):
    if not getattr(message, "embeds", None):
        return ""
    wanted = str(contains).casefold()
    for field in message.embeds[0].fields:
        if wanted in str(field.name or "").casefold():
            return str(field.value or "").replace("**", "").strip()
    return ""


def _machine_money_from_text(value):
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    return int(digits) if digits else 0


def _machine_datetime_from_text(value):
    text = str(value or "").replace("**", "").strip().partition("\n")[0].strip()
    for fmt in ("%d/%m/%Y à %H:%M", "%d/%m/%Y %H:%M", "%d/%m/%Y - %H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=TIMEZONE)
        except ValueError:
            pass
    return None


async def refresh_machine_time_displays():
    """Ajoute le Québec uniquement aux cartes des machines encore en cours."""
    await bot.wait_until_ready()
    by_message = {}
    for reminder in load_reminders():
        if str(reminder.get("channel_id")) != str(MACHINE_REMINDER_CHANNEL_ID):
            continue
        for message_id in [reminder.get("message_id"), *(reminder.get("message_ids") or [])]:
            if message_id:
                by_message[str(message_id)] = reminder
    updated = 0
    failed = 0
    try:
        channel = bot.get_channel(MACHINE_REMINDER_CHANNEL_ID) or await bot.fetch_channel(MACHINE_REMINDER_CHANNEL_ID)
        # Le scan retrouve les cartes anciennes, mais seules celles encore en
        # cours peuvent être modifiées.
        async for message in channel.history(limit=None, oldest_first=True):
            if not bot.user or message.author.id != bot.user.id or not message.embeds:
                continue
            if "MACHINE" not in str(message.embeds[0].title or "").upper():
                continue
            reminder = by_message.get(str(message.id), {})
            if any(reminder.get(key) for key in ("cancelled", "recovered", "finished_notified", "suppress_auto_reminders")):
                continue
            finish_field = next((field.value for field in message.embeds[0].fields
                                 if "Fin prévue" in (field.name or "")), None)
            finish = _machine_datetime_from_text(finish_field)
            if reminder.get("finish_at"):
                try:
                    finish = datetime.fromisoformat(reminder["finish_at"])
                except (ValueError, TypeError):
                    pass
            if finish is None:
                continue
            if finish.tzinfo is None:
                finish = finish.replace(tzinfo=TIMEZONE)
            if finish.astimezone(timezone.utc) <= datetime.now(timezone.utc):
                continue
            embed = discord.Embed.from_dict(message.embeds[0].to_dict())
            changed = False
            for index, field in enumerate(embed.fields):
                if not any(label in (field.name or "") for label in ("Lancement", "Fin prévue")):
                    continue
                value = _machine_datetime_from_text(field.value)
                if value is None:
                    continue
                # L'offset sauvegardé distingue les deux occurrences d'une heure
                # lors du passage à l'heure d'hiver.
                key = "launched_at" if "Lancement" in field.name else "finish_at"
                if reminder.get(key):
                    try:
                        saved = datetime.fromisoformat(reminder[key])
                        if machine_display_time(saved).partition("\n")[0] == str(field.value).partition("\n")[0]:
                            value = saved
                    except (ValueError, TypeError):
                        pass
                display = machine_display_time(value)
                if display != field.value:
                    embed.set_field_at(index, name=field.name, value=display, inline=False)
                    changed = True
            if changed:
                try:
                    # Aucun changement des boutons, montants, statuts ou mentions.
                    await message.edit(embeds=[embed, *message.embeds[1:]])
                    updated += 1
                    if updated % 10 == 0:
                        print(f"[MACHINES] Fuseau Québec : {updated} ancienne(s) carte(s) mise(s) à jour, parcours en cours.", flush=True)
                except discord.HTTPException as exc:
                    failed += 1
                    print(f"[MACHINES] Fuseau Québec : carte {message.id} non modifiée ({type(exc).__name__}).", flush=True)
                # Discord applique un quota plus strict aux messages anciens.
                await asyncio.sleep(6)
        print(f"[MACHINES] Fuseau Québec : {updated} ancienne(s) carte(s) mise(s) à jour, {failed} échec(s).", flush=True)
    except Exception as exc:
        print(f"[MACHINES] Fuseau Québec : parcours de l'historique interrompu ({type(exc).__name__}), {updated} carte(s) mise(s) à jour.", flush=True)


def _machine_parse_history_message(message, component_ids):
    """Lit les anciennes cartes Machines sans dépendre du JSON local."""
    if not getattr(message, "embeds", None):
        return None
    embed = message.embeds[0]
    title = str(embed.title or "")
    title_upper = title.upper()

    amount = _machine_money_from_text(_machine_embed_field(message, "Montant lancé"))
    if not amount:
        amount = _machine_money_from_text(_machine_embed_field(message, "Montant"))
    if not amount:
        collect = _machine_money_from_text(_machine_embed_field(message, "À récupérer"))
        if collect:
            amount = round(collect / 0.80)

    launched = _machine_datetime_from_text(_machine_embed_field(message, "Lancement"))
    finish = _machine_datetime_from_text(_machine_embed_field(message, "Fin prévue"))

    # Une fiche de rappel est créée au moment de la fin : sa date Discord est donc
    # une bonne valeur de secours si l'ancienne version n'affichait pas les heures.
    created = message.created_at.astimezone(TIMEZONE)
    if finish is None and ("TERMIN" in title_upper or "RAPPEL" in title_upper):
        finish = created
    if launched is None and finish is not None:
        launched = machine_time_shift(finish, -MACHINE_DURATION)
    if launched is None:
        launched = created
    if finish is None:
        finish = machine_time_shift(launched, MACHINE_DURATION)

    status = _machine_embed_field(message, "Statut").upper()
    recovered = "RÉCUPÉRÉE" in status and "NON" not in status
    cancelled = "ANNUL" in title_upper

    user_id = None
    launcher_value = _machine_embed_field(message, "Lancée par")
    mention = re.search(r"<@!?(\d+)>", launcher_value)
    if mention:
        user_id = int(mention.group(1))

    return {
        "amount": int(amount or 0),
        "launched_at": launched.isoformat(),
        "finish_at": finish.isoformat(),
        "recovered": recovered,
        "cancelled": cancelled,
        "user_id": user_id,
    }


def _machine_current_sheet_snapshot():
    """Une seule lecture Google pour rattacher les vieilles cartes de la semaine courante."""
    try:
        ws = worksheet(MACHINES_SHEET_ID, MACHINES_WORKSHEET)
        values = ws.get(f"B{MACHINES_FIRST_ROW}:H174")
    except Exception as exc:
        print(f"[MACHINES] Lecture Sheet pour migration impossible : {exc}")
        return []
    result = []
    for offset, row in enumerate(values):
        cells = list(row) + [""] * max(0, 7 - len(row))
        # B,C,D,E,F,G,H => indices 0,1,2,3,4,5,6
        result.append({
            "row": MACHINES_FIRST_ROW + offset,
            "date": str(cells[0]).strip(),
            "amount": _machine_money_from_text(cells[1]),
            "time": str(cells[3]).strip(),
            "launcher": str(cells[6]).strip().casefold(),
        })
    return result


def _machine_match_current_sheet_row(parsed, snapshot, guild):
    try:
        launched = datetime.fromisoformat(parsed["launched_at"])
        if launched.tzinfo is None:
            launched = launched.replace(tzinfo=TIMEZONE)
    except Exception:
        return None
    date_text = launched.astimezone(TIMEZONE).strftime("%d/%m/%Y")
    time_text = launched.astimezone(TIMEZONE).strftime("%H:%M")
    amount = int(parsed.get("amount") or 0)

    launcher = ""
    uid = parsed.get("user_id")
    if uid and guild:
        member = guild.get_member(int(uid))
        if member:
            launcher = member.display_name.casefold().strip()

    matches = []
    for item in snapshot:
        if item["date"] != date_text or item["time"] != time_text:
            continue
        if amount and item["amount"] and item["amount"] != amount:
            continue
        if launcher and item["launcher"] and item["launcher"] != launcher:
            continue
        matches.append(item["row"])
    return matches[0] if len(matches) == 1 else None


async def restore_machine_history_after_restart():
    """Réactive aussi les cartes Machines créées AVANT les versions persistantes.

    Le scan ne PATCH aucun message. Il reconstruit seulement le petit JSON local et
    enregistre les vues par message_id. Les vieux rappels ne se remettent pas à spammer.
    """
    await bot.wait_until_ready()
    cutoff = datetime.now(timezone.utc) - timedelta(days=MACHINE_HISTORY_DAYS)
    restored_launch = 0
    restored_status = 0
    restored_cancelled = 0
    reconstructed = 0
    adopted = 0

    try:
        channel = bot.get_channel(MACHINE_REMINDER_CHANNEL_ID) or await bot.fetch_channel(MACHINE_REMINDER_CHANNEL_ID)
        if not isinstance(channel, discord.abc.Messageable):
            raise ValueError("Le salon Discord configuré ne permet pas les messages.")
        guild = bot.get_guild(GUILD_ID)
        snapshot = await run_blocking(_machine_current_sheet_snapshot)
        reminders = load_reminders()
        by_id = {str(r.get("id")): r for r in reminders if r.get("id")}
        reliable_saved_ids = set(by_id)  # Le JSON prime sur les vieux embeds Discord.
        changed = False

        async for message in channel.history(limit=None, oldest_first=True, after=cutoff):
            if not bot.user or message.author.id != bot.user.id:
                continue
            component_ids = _machine_message_component_ids(message)
            reminder_id = _machine_id_from_component_ids(component_ids)
            if not reminder_id:
                continue

            parsed = _machine_parse_history_message(message, component_ids)
            if parsed is None:
                continue

            record = by_id.get(reminder_id)
            if record is None:
                record = {
                    "id": reminder_id,
                    "channel_id": MACHINE_REMINDER_CHANNEL_ID,
                    "amount": parsed["amount"],
                    "launched_at": parsed["launched_at"],
                    "finish_at": parsed["finish_at"],
                    "user_id": parsed.get("user_id"),
                    "recovered": bool(parsed.get("recovered")),
                    "finished_notified": False,
                    "historical_import": True,
                    "message_ids": [],
                }
                # Une vieille fiche doit répondre aux boutons, mais ne doit pas
                # recommencer à ping toutes les 15 minutes après une migration.
                try:
                    finish_dt = datetime.fromisoformat(record["finish_at"])
                    if finish_dt.tzinfo is None:
                        finish_dt = finish_dt.replace(tzinfo=TIMEZONE)
                    record["suppress_auto_reminders"] = (
                        datetime.now(TIMEZONE) - finish_dt > timedelta(hours=24)
                    )
                except Exception:
                    record["suppress_auto_reminders"] = True
                reminders.append(record)
                by_id[reminder_id] = record
                reconstructed += 1
                changed = True

            # Complète sans écraser les données fiables déjà enregistrées.
            for key in ("amount", "launched_at", "finish_at", "user_id"):
                if not record.get(key) and parsed.get(key):
                    record[key] = parsed[key]
                    changed = True

            mids = record.setdefault("message_ids", [])
            if str(message.id) not in {str(x) for x in mids}:
                mids.append(str(message.id))
                adopted += 1
                changed = True

            is_launch = any(cid.startswith(("machine_launch_again:", "machine_edit_time:", "machine_cancel:")) for cid in component_ids)
            is_status = any(cid.startswith(("machine_recovered:", "machine_recovered_launch:")) for cid in component_ids)
            is_cancelled = any(cid.startswith("machine_relaunch_cancelled:") for cid in component_ids) or parsed.get("cancelled")

            if is_launch:
                record["message_id"] = str(message.id)
                if record.get("sheet_row") is None:
                    matched_row = _machine_match_current_sheet_row(parsed, snapshot, guild)
                    if matched_row is not None:
                        record["sheet_row"] = matched_row
                        changed = True
                bot.add_view(MachineLaunchView(reminder_id, record.get("sheet_row")), message_id=message.id)
                restored_launch += 1

            if is_status:
                # Les anciennes cartes servent à récupérer les boutons. Elles ne
                # doivent JAMAIS écraser un état sauvegardé dans le JSON local,
                # qui contient notamment le recovered_at nécessaire à la compta.
                # Pour une migration sans JSON, le scan oldest_first conserve le
                # statut de la dernière carte vue (la plus récente).
                if reminder_id not in reliable_saved_ids:
                    record["recovered"] = bool(parsed.get("recovered"))
                record["finished_notified"] = True
                if not record.get("finish_message_id"):
                    record["finish_message_id"] = str(message.id)
                record["last_reminder_message_id"] = str(message.id)
                bot.add_view(
                    MachineRecoveredView(reminder_id, recovered=bool(record.get("recovered"))),
                    message_id=message.id,
                )
                restored_status += 1
                changed = True

            if is_cancelled:
                record["cancelled"] = True
                record["recovered"] = True
                record["suppress_auto_reminders"] = True
                bot.add_view(MachineRelaunchView(reminder_id), message_id=message.id)
                restored_cancelled += 1
                changed = True

        if changed:
            save_reminders(reminders)

        print(
            f"[MACHINES] Historique : {restored_launch} lancement(s), "
            f"{restored_status} rappel(s), {restored_cancelled} annulée(s) réactivé(s) ; "
            f"{reconstructed} suivi(s) reconstruit(s), {adopted} message(s) rattaché(s)."
        )
    except Exception as exc:
        print(f"[MACHINES] Restauration de l'historique impossible : {exc}")
        print("[MACHINES] Vérifie l'accès à l'historique du salon Employés et les permissions du bot.")


# Les modifications de vieilles fiches partagent le même quota Discord.
# L'enregistrement des boutons avec bot.add_view(...) ne fait AUCUN appel HTTP.
# Seules les corrections visuelles nécessaires sont espacées pour éviter les 429.
SALE_RESTORE_EDIT_INTERVAL = 4.0
_sale_restore_edit_lock = asyncio.Lock()
_sale_restore_next_edit = 0.0


async def sale_restore_edit(message, view):
    """Sérialise et espace les PATCH de migration/expiration des fiches Sales."""
    global _sale_restore_next_edit
    async with _sale_restore_edit_lock:
        loop = asyncio.get_running_loop()
        delay = _sale_restore_next_edit - loop.time()
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            return await message.edit(view=view)
        finally:
            # discord.py attend automatiquement le Retry-After d'un éventuel 429.
            # On attend encore entre deux éditions, y compris après un échec.
            _sale_restore_next_edit = loop.time() + SALE_RESTORE_EDIT_INTERVAL


def sale_message_needs_refresh(message, is_panel=False, expired=False):
    """Ne modifie pas une fiche qui possède déjà les bons boutons."""
    components = [component for row in message.components for component in getattr(row, "children", [])]
    ids = {custom_id: getattr(component, "label", None)
           for component in components
           if isinstance(custom_id := getattr(component, "custom_id", None), str)}
    if is_panel:
        return (ids.get("panel:reset_week") is None
                or ids.get("panel:add_sale") != "Ajouter du sale"
                or "panel:add_employee" not in ids or "panel:add_group" not in ids
                or "panel:delete_employee" not in ids or "panel:delete_group" not in ids)
    if expired:
        return any(not getattr(component, "disabled", False) for component in components)
    return (any(key.startswith("sale_reset_week:") for key in ids)
            or not any(key.startswith("sale_add_new:") for key in ids)
            or not any(key.startswith("sale_edit:") for key in ids)
            or not any(key.startswith("sale_cancel:") for key in ids)
            or any(key.startswith("sale_add_new:") and value != "Ajouter du sale"
                   for key, value in ids.items())
            or any(getattr(component, "disabled", False) for component in components))


async def expire_recorded_sales(channel):
    """Désactive les fiches de plus de 365 jours et allège le petit fichier JSON."""
    expired_ids = []
    data = load_sale_messages()
    for message_id, record in data.items():
        if not isinstance(record, dict) or "row" not in record:
            continue
        # Les fiches sans date (versions précédentes) sont vérifiées une fois.
        if record.get("created_at") and not sale_record_is_expired(record):
            continue
        try:
            message = await channel.fetch_message(int(message_id))
        except discord.NotFound:
            expired_ids.append(message_id)
            continue
        except (ValueError, discord.Forbidden, discord.HTTPException) as exc:
            print(f"[SALE] Impossible de vérifier la fiche {message_id}: {exc}")
            continue

        if not sale_is_expired(message):
            if not record.get("created_at"):
                # On complète les anciennes fiches sans changer leur feuille.
                current = load_sale_messages()
                if message_id in current:
                    current[message_id]["created_at"] = message.created_at.isoformat()
                    save_sale_messages(current)
            continue

        try:
            row = int(record["row"])
            if sale_message_needs_refresh(message, expired=True):
                await sale_restore_edit(message, SaleStatusView(row, disabled=True))
            expired_ids.append(message_id)
        except (TypeError, ValueError, discord.Forbidden, discord.HTTPException) as exc:
            print(f"[SALE] Impossible d'expirer la fiche {message_id}: {exc}")

    if expired_ids:
        current = load_sale_messages()
        for message_id in expired_ids:
            current.pop(message_id, None)
        save_sale_messages(current)
    return len(expired_ids)


async def restore_sale_views_after_restart():
    for channel_id in SALES_CHANNEL_IDS:
        await restore_sale_channel_views_after_restart(channel_id)


async def restore_sale_channel_views_after_restart(channel_id: int):
    """
    Restaure toutes les fiches (y compris terminées) créées depuis moins de
    365 jours. Au premier démarrage, migre une fois les fiches historiques.
    """
    await bot.wait_until_ready()
    restored = 0
    updated = 0
    expired = 0
    panels = 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=SALE_ACTIVE_DAYS)
    try:
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            raise ValueError("Le salon Discord configuré ne permet pas les messages.")
        # On rescane toujours la période réellement conservée. Avec ~2 sales/jour,
        # cela reste très léger et évite qu'un ancien flag de migration fasse oublier
        # une fiche créée avant une mise à jour du bot.
        async for message in channel.history(
            limit=None, oldest_first=False, after=cutoff
        ):
            if bot.user is None or message.author.id != bot.user.id:
                continue

            component_ids = {
                getattr(component, "custom_id", None)
                for action_row in message.components
                for component in getattr(action_row, "children", [])
            }
            is_panel = "panel:add_sale" in component_ids
            if is_panel:
                panels += 1
                bot.add_view(SalesPanel(), message_id=message.id)
                if sale_message_needs_refresh(message, is_panel=True):
                    try:
                        await sale_restore_edit(message, SalesPanel())
                        updated += 1
                    except discord.HTTPException as exc:
                        print(f"[SALE] Panneau {message.id} non mis à jour : {exc}")
                continue

            row = sale_message_row(message)
            if row is None:
                continue

            if sale_is_expired(message):
                # Uniquement lors de la première migration : les vieilles fiches
                # restent dans Discord, avec tous leurs boutons désactivés.
                if sale_message_needs_refresh(message, expired=True):
                    try:
                        await sale_restore_edit(message, SaleStatusView(row, disabled=True))
                        updated += 1
                    except discord.HTTPException as exc:
                        print(f"[SALE] Fiche {message.id} non expirée visuellement : {exc}")
                expired += 1
                continue

            # Les fiches annulées restent visibles mais ne sont jamais réactivées.
            record = load_sale_messages().get(str(message.id), {})
            if isinstance(record, dict) and record.get("cancelled"):
                if sale_message_needs_refresh(message, expired=True):
                    try:
                        await sale_restore_edit(message, SaleStatusView(row, disabled=True))
                        updated += 1
                    except discord.HTTPException as exc:
                        print(f"[SALE] Fiche annulée {message.id} non désactivée : {exc}")
                continue

            # L'ID Discord distingue les fiches, même si deux semaines ont la
            # même ligne dans le Sheet. Aucun filtrage sur le statut Terminé.
            bot.add_view(SaleStatusView(row), message_id=message.id)
            bot.add_view(LegacySaleResetView(row), message_id=message.id)
            restored += 1

            record = load_sale_messages().get(str(message.id), {})
            if not isinstance(record, dict) or not record.get("created_at"):
                # Ne pas supposer qu'une ancienne fiche appartient à En cours :
                # sa feuille sera retrouvée par son empreinte au premier clic.
                register_sale_message(
                    message, row, record.get("worksheet") if isinstance(record, dict) else None
                )

            if sale_message_needs_refresh(message):
                try:
                    await sale_restore_edit(message, SaleStatusView(row))
                    updated += 1
                except discord.HTTPException as exc:
                    print(f"[SALE] Fiche {message.id} non mise à jour : {exc}")

        # Marque seulement la version de migration exécutée ; ce fichier ne limite
        # plus le scan des 365 derniers jours.
        try:
            SALE_HISTORY_MIGRATION_FILE.write_text(
                datetime.now(timezone.utc).isoformat(), encoding="utf-8"
            )
        except Exception:
            pass

        expired += await expire_recorded_sales(channel)
        print(
            f"[SALE] Restart : {restored} fiche(s) de moins de 365 jours restaurée(s) "
            f"(terminées incluses), {expired} expirée(s), "
            f"{panels} panneau(x), {updated} message(s) actualisé(s)."
        )
    except Exception as exc:
        print(f"[SALE] Restauration des fiches sur 365 jours impossible : {exc}")
        print("[SALE] Vérifie l'accès à l'historique du salon Sales et les permissions du bot.")


async def sale_expiration_worker():
    """Fait expirer les boutons en cours de semaine sans attendre un reboot."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(3600)
        for channel_id in SALES_CHANNEL_IDS:
            try:
                channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
                if not isinstance(channel, discord.abc.Messageable):
                    raise ValueError("Le salon Discord configuré ne permet pas les messages.")
                count = await expire_recorded_sales(channel)
                if count:
                    print(f"[SALE] Expiration : {count} fiche(s) arrivées à 365 jours.")
            except Exception as exc:
                print(f"[SALE] Expiration automatique impossible : {exc}")


_sale_restore_started = False


async def _sale_progress_restore_then_signal(coro, signal, name):
    try:
        await coro()
    except Exception as exc:
        print(f"[PROGRESSION SALE] Erreur pendant restauration {name}: {exc}")
    finally:
        signal.set()


@bot.event
async def on_ready():
    global _sale_restore_started
    if _sale_restore_started:
        return
    _sale_restore_started = True
    if "sales" in _tenant_runtime_active_modules:
        asyncio.create_task(_sale_progress_restore_then_signal(
            restore_sale_views_after_restart,
            _sale_progress_sale_history_ready, "sales"
        ))
    else:
        _sale_progress_sale_history_ready.set()
    if "machines" in _tenant_runtime_active_modules:
        asyncio.create_task(_sale_progress_restore_then_signal(
            restore_machine_history_after_restart,
            _sale_progress_machine_history_ready, "machines"
        ))
        asyncio.create_task(restore_machine_panels_after_restart())
        asyncio.create_task(refresh_machine_time_displays())
    else:
        _sale_progress_machine_history_ready.set()
    if "tombola" in _tenant_runtime_active_modules:
        asyncio.create_task(restore_tombola_views_after_restart())
        asyncio.create_task(restore_tombola_legacy_panels_after_restart())


@bot.event
async def on_raw_message_delete(payload: discord.RawMessageDeleteEvent):
    """Alerte si un message public Machines est supprimé (quelle qu'en soit la cause)."""
    if payload.channel_id != MACHINE_REMINDER_CHANNEL_ID:
        return

    deleted_id = str(payload.message_id)
    reminder = next(
        (
            r for r in load_reminders()
            if deleted_id in ({
                str(r.get("message_id") or ""),
                str(r.get("finish_message_id") or ""),
                str(r.get("last_reminder_message_id") or "")
            } | {str(x) for x in (r.get("message_ids") or [])})
        ),
        None
    )
    if reminder is None:
        return

    warning = (
        f"⚠️ **Message public Machines réellement supprimé**\n"
        f"🆔 Message : `{deleted_id}`\n"
        f"⚙️ Machine : `{reminder.get('id')}`\n"
        "ℹ️ Le bouton Récupérée de ce bot ne supprime pas les messages. "
        "Vérifie qu'une autre instance ou un autre bot ne les efface pas."
    )
    print(f"[MACHINES] ALERTE suppression du message {deleted_id} (machine {reminder.get('id')})")
    try:
        await send_machine_log(warning)
    except Exception as exc:
        print(f"[MACHINES] Impossible de journaliser la suppression : {exc}")


@bot.event
async def setup_hook():
    if "sales" in _tenant_runtime_active_modules:
        # Generic IDs must never be shared between guild runtimes. Saved message
        # IDs and the history restoration below bind each view to its own server.
        for message_id, record in load_sale_messages().items():
            try:
                if sale_record_is_expired(record):
                    continue
                row = int(record["row"])
                bot.add_view(SaleStatusView(row, disabled=bool(record.get("cancelled"))), message_id=int(message_id))
                if not record.get("cancelled"):
                    bot.add_view(LegacySaleResetView(row), message_id=int(message_id))
            except (KeyError, TypeError, ValueError):
                print(f"[SALE] Association locale invalide : {message_id}")
        bot.loop.create_task(weekly_sales_reset_worker())
        bot.loop.create_task(sale_expiration_worker())
    if "machines" in _tenant_runtime_active_modules:
        restore_machine_views_and_reminders()
        bot.loop.create_task(machine_recovery_repeat_loop())
        bot.loop.create_task(machine_weekly_stats_reset_loop())
    if "sales" in _tenant_runtime_active_modules and "machines" in _tenant_runtime_active_modules:
        bot.loop.create_task(sale_progress_worker())
    if "tombola" in _tenant_runtime_active_modules:
        register_saved_tombola_views()

    # Les commandes sont déjà enregistrées côté Discord.
    # On évite de les resynchroniser à chaque redémarrage du service,
    # ce qui provoquait des 429 pendant les tests/redémarrages rapprochés.
    #
    # Pour forcer une synchro après ajout/suppression/renommage d'une
    # commande slash, mettre SYNC_DISCORD_COMMANDS=1 dans le .env,
    # redémarrer UNE fois, puis remettre la variable à 0 (ou la supprimer).
    if os.getenv("SYNC_DISCORD_COMMANDS", "0").strip().lower() in {"1", "true", "yes", "on"}:
        try:
            synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
            print(f"[DISCORD] {len(synced)} commande(s) slash synchronisée(s).")
        except discord.HTTPException as exc:
            print(f"[DISCORD] Synchronisation des commandes impossible pour le moment : {exc}")
    else:
        print("[DISCORD] Synchronisation slash ignorée au démarrage (SYNC_DISCORD_COMMANDS=0).")


if not globals().get("_tenant_bot_facade"):
    if not DISCORD_TOKEN:
        raise RuntimeError("La variable d'environnement DISCORD_TOKEN n'est pas définie.")
    if os.getenv("BOT_MULTI_GUILD_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}:
        from bot_guilds import install_multi_guild_runtime
        guild_runtime_manager = install_multi_guild_runtime(bot, globals())
    bot.run(DISCORD_TOKEN)
