"""Google Sheets checks and dropdown updates for a single saved Discord setup.

This module never imports or starts the bot.  Connection checks are read-only;
the explicit sync operation changes data-validation rules only, never cell
values, formulas, archives, or sharing permissions.
"""
from __future__ import annotations

import hmac
import os
import re
import unicodedata
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
CONTROL_WORKSHEET = "Configuration bot"
CONTROL_RANGE = "'Configuration bot'!A1"
SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
)
_SHEET_ID = re.compile(r"[A-Za-z0-9_-]{20,200}\Z")


class GuildSheetsError(ValueError):
    """A safe error suitable for the setup page; no provider payload is exposed."""

    def __init__(self, message: str, code: str = "google_unavailable"):
        super().__init__(message)
        self.code = code


def _sheet_id(value: Any) -> str:
    if not isinstance(value, str) or not _SHEET_ID.fullmatch(value):
        raise GuildSheetsError("Identifiant Google Sheet invalide.", "invalid_sheet_id")
    return value


def _credentials():
    from google.oauth2.service_account import Credentials

    path = Path(os.getenv("GOOGLE_APPLICATION_CREDENTIALS", str(ROOT / "google_credentials.json")))
    try:
        return Credentials.from_service_account_file(path, scopes=SCOPES)
    except Exception:
        raise GuildSheetsError(
            "La connexion Google du bot n'est pas configurée. Contacte son responsable.",
            "google_not_configured",
        ) from None


def google_service_email() -> str:
    """Only the public sharing address is returned; credentials stay on the server."""
    return _credentials().service_account_email


def get_setup_google_client():
    try:
        import gspread

        client = gspread.authorize(_credentials())
        client.set_timeout(15)
        return client
    except GuildSheetsError:
        raise
    except Exception:
        raise GuildSheetsError("La connexion Google est indisponible.") from None


def _client(client):
    return client if client is not None else get_setup_google_client()


def verify_sheet_control(sheet_id: str, token: str, client=None) -> bool:
    """Check a server-bound proof without reading unrelated workbook contents.

    The setup service generates the token, binds it to the authenticated guild,
    then asks the owner to put it in Configuration bot!A1 in their own copy.
    The caller must perform this check before exposing workbook metadata or
    accepting a new binding.  Merely knowing a spreadsheet ID is not proof.
    """
    sheet_id = _sheet_id(sheet_id)
    if not isinstance(token, str) or not 20 <= len(token) <= 256 or not token.isascii():
        raise GuildSheetsError("Code de vérification invalide ou expiré.", "invalid_control_token")
    try:
        result = _client(client).http_client.values_get(
            sheet_id, CONTROL_RANGE, params={"valueRenderOption": "FORMATTED_VALUE"}
        )
        values = result.get("values", [])
        actual = values[0][0] if values and values[0] else ""
    except Exception:
        raise GuildSheetsError(
            "Vérification impossible. Partage ta copie avec le compte du bot, puis crée "
            "l'onglet « Configuration bot » et colle le code indiqué dans A1.",
            "sheet_control_unverified",
        ) from None
    if not isinstance(actual, str) or not hmac.compare_digest(actual.encode("utf-8"), token.encode("utf-8")):
        raise GuildSheetsError(
            "Le code ne correspond pas. Colle le code de ce serveur dans « Configuration bot », cellule A1.",
            "sheet_control_unverified",
        )
    return True


def _drive_api_disabled(error: Exception) -> bool:
    """Recognize Google's structured API-disabled error without exposing it."""
    response = getattr(error, "response", None)
    if getattr(response, "status_code", None) != 403:
        return False
    try:
        payload = response.json()
        details = payload.get("error", {})
        if not isinstance(details, dict):
            return False
        reasons = {item.get("reason") for field in ("errors", "details")
                   for item in details.get(field, []) if isinstance(item, dict)
                   and isinstance(item.get("reason"), str)}
        return bool(reasons.intersection({"accessNotConfigured", "SERVICE_DISABLED"}))
    except Exception:
        return False


def _can_edit(client, sheet_id: str):
    """Drive capabilities verifies write access without writing a probe cell."""
    try:
        response = client.http_client.request(
            "get", f"https://www.googleapis.com/drive/v3/files/{sheet_id}",
            params={"fields": "capabilities(canEdit)", "supportsAllDrives": True},
        )
        can_edit = response.json().get("capabilities", {}).get("canEdit")
    except Exception as error:
        if _drive_api_disabled(error):
            raise GuildSheetsError(
                "Le responsable du bot doit activer l’API Google Drive dans son projet Google Cloud, "
                "puis réessayer la vérification des fichiers.",
                "google_drive_disabled",
            ) from None
        raise GuildSheetsError(
            "Impossible de vérifier le droit de modification Google. Vérifie le partage "
            "et l'activation des API Google Sheets et Google Drive.",
            "sheet_edit_access_unknown",
        ) from None
    if can_edit is not True:
        raise GuildSheetsError(
            "Le compte du bot doit avoir le droit « Éditeur » sur ce Google Sheet.",
            "sheet_not_writable",
        )


def _normalized(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value)).casefold()
    return "".join(char for char in text if char.isalnum() and not unicodedata.combining(char))


_SALES_HEADERS = {
    0: {"etat", "statut"},
    1: {"daterecu", "daterecue", "datereception"},
    2: {"daterendu", "daterendue", "daterestitution"},
    3: {"nomdugroupe", "groupe"},
    4: {"employe", "employes"},
    5: {"joueurquidonne", "quidonne", "joueurdonneur"},
    6: {"joueurquirecupere", "quirecupere", "joueurquichercle"},
    7: {"sommeablanchir", "montantablanchir"},
    9: {"entreprise", "gainentreprise"},
    10: {"groupe", "gaingroupe"},
}


def _worksheet_shape(sheet, *, sales: bool):
    minimum_rows, minimum_columns = (10, 12) if sales else (8, 8)
    if sheet.row_count < minimum_rows or sheet.col_count < minimum_columns:
        raise GuildSheetsError(
            "Le Google Sheet ne possède pas la structure du modèle fourni.", "invalid_sheet_layout"
        )
    if sales:
        values = sheet.get("B8:L8")
        row = values[0] if values else []
        for index, expected in _SALES_HEADERS.items():
            if index >= len(row) or _normalized(row[index]) not in expected:
                raise GuildSheetsError(
                    "Les colonnes du suivi Sale ne correspondent pas au modèle. "
                    "Utilise une copie du modèle sans déplacer les colonnes.",
                    "invalid_sales_layout",
                )
    else:
        # Older machine models use different header rows.  Require the four
        # columns the bot writes, keeping their positions fixed (B, C, E, H).
        values = sheet.get("B1:H7")
        columns = {index: {_normalized(row[index]) for row in values if index < len(row)}
                   for index in (0, 1, 3, 6)}
        expected = {
            0: {"date", "datelancement", "datedelancement", "semaine"},
            1: {"montant", "montantlance", "somme", "montantablanchir", "sommeablanchir", "combien"},
            3: {"heure", "heurelancement", "heuredelancement", "heures"},
            6: {"employe", "employes", "lancepar", "lanceepar", "personne", "nom"},
        }
        if any(not columns[index].intersection(choices) for index, choices in expected.items()):
            raise GuildSheetsError(
                "Les colonnes Machines ne correspondent pas au modèle (date B, montant C, heure E, personne H).",
                "invalid_machines_layout",
            )


def _open_targets(client, module: dict, *, sales: bool):
    sheet_id = _sheet_id(module.get("sheet_id"))
    _can_edit(client, sheet_id)
    try:
        book = client.open_by_key(sheet_id)
        sheets = {sheet.title: sheet for sheet in book.worksheets()}
    except Exception:
        raise GuildSheetsError(
            "Google Sheet inaccessible. Vérifie le lien et le partage avec le compte du bot.",
            "sheet_inaccessible",
        ) from None
    working = module.get("worksheet") or ("En cours" if sales else "Blanchiments")
    if not isinstance(working, str) or not working.strip() or (sales and working == "Modele"):
        raise GuildSheetsError("Nom d'onglet de travail invalide.", "invalid_worksheet")
    names = [working, "Modele"] if sales else [working]
    targets = []
    for name in names:
        if name not in sheets:
            raise GuildSheetsError(
                f"L'onglet « {name} » est absent. Utilise une copie complète du modèle.",
                "missing_worksheet",
            )
        sheet = sheets[name]
        try:
            _worksheet_shape(sheet, sales=sales)
        except GuildSheetsError:
            raise
        except Exception:
            raise GuildSheetsError("Impossible de lire la structure du modèle Google.") from None
        targets.append(sheet)
    return book, targets


def _modules(config: dict) -> dict:
    modules = config.get("modules", {})
    if not isinstance(modules, dict):
        raise GuildSheetsError("Configuration des fonctions invalide.", "invalid_config")
    return modules


def validate_setup_sheets(config: dict, client=None) -> dict:
    """Read-only structure/access check for configured modules; blanks are skipped."""
    modules = _modules(config)
    report = {"ok": True, "modules": {}}
    from guild_setup import storage_mode
    enabled = [(name, modules.get(name)) for name in ("sales", "machines")
               if modules.get(name) and storage_mode(config, name) == "google_sheets"]
    if not enabled:
        return report
    client = _client(client)
    for name, module in enabled:
        if not isinstance(module, dict):
            raise GuildSheetsError("Configuration Google invalide.", "invalid_config")
        _, targets = _open_targets(client, module, sales=name == "sales")
        report["modules"][name] = {"ok": True, "sheet_id": module["sheet_id"],
                                   "worksheets": [sheet.title for sheet in targets]}
    return report


def _choice_lists(config: dict):
    employees = config.get("employees", [])
    groups = config.get("groups", [])
    if not isinstance(employees, list) or not isinstance(groups, list) or len(employees) > 25 or len(groups) > 25:
        raise GuildSheetsError("Les listes acceptent au maximum 25 personnes et 25 groupes.", "invalid_choices")
    labels, identifiers, names = [], [], []
    for person in employees:
        if not isinstance(person, dict):
            raise GuildSheetsError("Personne invalide.", "invalid_choices")
        name, identifier = person.get("name"), person.get("id")
        if (not isinstance(name, str) or not name.strip() or len(name.strip()) > 70
                or name.lstrip().startswith("=") or not isinstance(identifier, str)
                or not identifier.isascii() or not identifier.isdigit() or len(identifier) > 20):
            raise GuildSheetsError("Chaque personne doit avoir un nom et un ID numérique valides.", "invalid_choices")
        name = name.strip()
        label = name if name.endswith(" " + identifier) else f"{name} {identifier}"
        if identifier in identifiers or name.casefold() in names:
            raise GuildSheetsError("Une personne ou un ID est présent plusieurs fois.", "invalid_choices")
        labels.append(label)
        identifiers.append(identifier)
        names.append(name.casefold())
    group_values = []
    for group in groups:
        if (not isinstance(group, str) or not group.strip() or len(group.strip()) > 100
                or group.lstrip().startswith("=")):
            raise GuildSheetsError("Nom de groupe invalide.", "invalid_choices")
        if group.strip().casefold() in {value.casefold() for value in group_values}:
            raise GuildSheetsError("Un groupe est présent plusieurs fois.", "invalid_choices")
        group_values.append(group.strip())
    return group_values, labels, identifiers


def sales_dropdown_requests(sheets, employees: list[dict], groups: list[str]) -> list[dict]:
    """Build a validation-only batch.  Useful for offline previews and tests."""
    group_values, labels, identifiers = _choice_lists({"employees": employees, "groups": groups})
    requests = []
    for sheet in sheets:
        if sheet.row_count < 10 or sheet.col_count < 8:
            raise GuildSheetsError("Le modèle ne contient pas de lignes de saisie.", "invalid_sheet_layout")
        for column, values in ((4, group_values), (5, labels), (6, identifiers), (7, identifiers)):
            validation = {"range": {"sheetId": sheet.id, "startRowIndex": 9,
                                     "endRowIndex": sheet.row_count,
                                     "startColumnIndex": column, "endColumnIndex": column + 1}}
            if values:
                validation["rule"] = {"condition": {"type": "ONE_OF_LIST",
                    "values": [{"userEnteredValue": value} for value in values]},
                    "strict": True, "showCustomUi": True}
            # An omitted rule removes an old validation; an empty ONE_OF_LIST is invalid.
            requests.append({"setDataValidation": validation})
    return requests


def sync_sale_dropdowns(config: dict, client=None) -> dict:
    """Explicitly sync only the saved sales setup's current and template dropdowns."""
    module = _modules(config).get("sales")
    from guild_setup import storage_mode
    if storage_mode(config, "sales") == "local":
        return {"ok": True, "skipped": True, "reason": "local_storage", "updated_ranges": 0}
    if not module:
        return {"ok": True, "skipped": True, "reason": "sales_disabled", "updated_ranges": 0}
    if not isinstance(module, dict):
        raise GuildSheetsError("Configuration Sale invalide.", "invalid_config")
    # Validate choices before opening Google; validate both tabs before any write.
    _choice_lists(config)
    client = _client(client)
    book, targets = _open_targets(client, module, sales=True)
    requests = sales_dropdown_requests(targets, config.get("employees", []), config.get("groups", []))
    try:
        book.batch_update({"requests": requests})
    except Exception:
        raise GuildSheetsError(
            "La mise à jour des listes Google a échoué. Vérifie les droits Éditeur "
            "et les protections des colonnes E à H, puis réessaie.",
            "dropdown_sync_failed",
        ) from None
    return {"ok": True, "sheet_id": module["sheet_id"],
            "worksheets": [sheet.title for sheet in targets], "updated_ranges": len(requests)}
