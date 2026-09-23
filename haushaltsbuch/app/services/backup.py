"""Portables JSON-Backup (Export/Import) aller fachlichen Daten.

Zusaetzlich zum Supervisor-Backup (1:1-Snapshot des Datenordners) liefert dieses Modul ein
menschenlesbares, von DB-IDs unabhaengiges Format, mit dem sich Daten in eine andere/frische
Instanz uebernehmen lassen (z.B. Test- -> Produktiv-Instanz).

Format (ein JSON-Dokument, ``meta`` steht bewusst zuerst)::

    {"meta": {"format": "haushaltsbuch-backup", "schema_version": 1, "app_version": "...",
              "exported_at": "...", "included_groups": [...], "counts": {...}},
     "accounts": [...], "categories": [...], "mapping_profiles": [...],
     "categorization_rules": [...], "budgets": [...],
     "transactions": [...], "transaction_splits": [...], "rejected_transfer_pairs": [...]}

Jede Entitaet traegt eine exportinterne Kennung ``export_id`` (UUID); Verknuepfungen zeigen
auf diese Kennung, nie auf rohe DB-IDs. Beim Import entstehen neue Zeilen, eine Zuordnungs-
tabelle (export_id -> neues Objekt) loest alle Fremdschluessel auf.

Datengruppen (auswaehlbar bei Export UND Import): ``accounts``, ``categories``,
``mapping_profiles``, ``categorization_rules`` (Kategorisierungsregeln in Prioritaetsreihenfolge),
``budgets`` (Monatsbudgets je Kategorie), ``transactions`` (inkl. Bargeld-Splits und den vom Nutzer
abgelehnten Umbuchungs-Vorschlaegen). ``transactions`` setzt ``accounts`` + ``categories`` voraus,
``categorization_rules`` und ``budgets`` setzen ``categories`` voraus.

Kategorien tragen das optionale Feld ``type`` ("einnahme"/"ausgabe"/null, nur an Oberkategorien); fehlt es
(Backup aus aelterer Version), bestimmt der Import den Typ wie die Datenbank-Migration.

Die Abschnitte ``categorization_rules`` und ``budgets`` sind optional (aeltere Dateien enthalten sie nicht);
das Format bleibt dadurch abwaertskompatibel (schema_version unveraendert).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import delete, func
from sqlmodel import Session, select

from app.models import (
    CATEGORY_TYPES,
    RULE_FIELDS,
    RULE_MODES,
    RULE_OPERATORS,
    SYSTEM_CATEGORY_DEFAULT_NAMES,
    UMBUCHUNG_KEY,
    Account,
    CategorizationRule,
    Category,
    CategoryBudget,
    MappingProfile,
    RejectedTransferPair,
    Transaction,
    TransactionSplit,
    TransactionType,
)
from app.services.category_types import backfill_category_types
from app.version import get_app_version

BACKUP_FORMAT = "haushaltsbuch-backup"
# Versionsnummer des BACKUP-FORMATS (unabhaengig von der App-Version). Bei inkompatiblen
# Aenderungen erhoehen; aeltere Versionen ab MIN_SCHEMA_VERSION bleiben importierbar.
SCHEMA_VERSION = 1
MIN_SCHEMA_VERSION = 1

GROUPS = ("accounts", "categories", "mapping_profiles", "categorization_rules", "budgets", "transactions")
GROUP_LABELS = {
    "accounts": "Konten",
    "categories": "Kategorien",
    "mapping_profiles": "Mapping-Profile",
    "categorization_rules": "Kategorisierungsregeln",
    "budgets": "Budgets",
    "transactions": "Buchungen (inkl. Bargeld-Splits)",
}
# Abhaengigkeiten: Buchungen referenzieren zwingend Konten und Kategorien; Regeln und Budgets Kategorien.
REQUIRES = {
    "transactions": ("accounts", "categories"),
    "categorization_rules": ("categories",),
    "budgets": ("categories",),
}

CONFIRM_WORD = "LÖSCHEN"


class BackupError(Exception):
    """Fehler mit nutzerverstaendlicher Meldung (Datei ungueltig, Auswahl unzulaessig, ...)."""


class ImportFailed(BackupError):
    """Import wurde abgebrochen und zurueckgerollt."""


def app_version() -> str:
    return get_app_version()


def with_dependencies(groups: Iterable[str]) -> list[str]:
    """Normalisiert eine Gruppenauswahl: nur bekannte Gruppen, Abhaengigkeiten ergaenzt,
    in fester Reihenfolge."""
    selected = {g for g in groups if g in GROUPS}
    for group in list(selected):
        selected.update(REQUIRES.get(group, ()))
    return [g for g in GROUPS if g in selected]


# ----------------------------------------------------------------------------------------
# Feld-Spezifikation (Import-Toleranz)
# ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class F:
    name: str
    required: bool = False
    default: Any = None
    warn_missing: bool = True


ENTITY_FIELDS: dict[str, list[F]] = {
    "accounts": [
        F("iban", required=True),
        F("display_name", required=True),
        F("bank_name"),
        F("starting_balance", warn_missing=False),
        F("created_at", warn_missing=False),
    ],
    "categories": [F("name", required=True), F("system_key"), F("type", warn_missing=False)],
    "mapping_profiles": [
        F("name", required=True),
        F("date_column", required=True),
        F("payee_column", required=True),
        F("purpose_column", required=True),
        F("amount_column", required=True),
        F("delimiter", default=","),
        F("decimal_separator", default="."),
        F("encoding", default="utf-8"),
        F("date_format", default="%Y-%m-%d"),
        F("header_row_index", default=0),
        F("created_at", warn_missing=False),
    ],
    "categorization_rules": [
        F("field", required=True),
        F("operator", required=True),
        F("value", required=True),
        F("mode", default="assign", warn_missing=False),
        F("created_at", warn_missing=False),
    ],
    "budgets": [F("monthly_amount", required=True)],
    "transactions": [
        F("booking_date", required=True),
        F("payee", required=True),
        F("amount", required=True),
        F("purpose"),
        F("transaction_type"),
        F("comment"),
        F("created_at", warn_missing=False),
    ],
    "transaction_splits": [F("amount", required=True), F("created_at", warn_missing=False)],
    "rejected_transfer_pairs": [F("created_at", warn_missing=False)],
}

# Verweisfelder: name -> (Ziel-Abschnitt, Pflicht?)
REF_FIELDS: dict[str, dict[str, tuple[str, bool]]] = {
    "categories": {"parent": ("categories", False)},
    "categorization_rules": {"category": ("categories", True)},
    "budgets": {"category": ("categories", True)},
    "transactions": {
        "account": ("accounts", True),
        "category": ("categories", False),
        "suggested_category": ("categories", False),
        "counter_transaction": ("transactions", False),
    },
    "transaction_splits": {
        "transaction": ("transactions", True),
        "category": ("categories", True),
    },
    "rejected_transfer_pairs": {
        "transaction_a": ("transactions", True),
        "transaction_b": ("transactions", True),
    },
}

SECTION_LABELS = {
    "accounts": "Konten",
    "categories": "Kategorien",
    "mapping_profiles": "Mapping-Profile",
    "categorization_rules": "Kategorisierungsregeln",
    "budgets": "Budgets",
    "transactions": "Buchungen",
    "transaction_splits": "Bargeld-Splits",
    "rejected_transfer_pairs": "Abgelehnte Umbuchungs-Vorschläge",
}
SECTION_GROUP = {
    "accounts": "accounts",
    "categories": "categories",
    "mapping_profiles": "mapping_profiles",
    "categorization_rules": "categorization_rules",
    "budgets": "budgets",
    "transactions": "transactions",
    "transaction_splits": "transactions",
    "rejected_transfer_pairs": "transactions",
}
# Reihenfolge, in der die Abschnitte validiert/importiert werden
SECTIONS = tuple(SECTION_GROUP)


# ----------------------------------------------------------------------------------------
# EXPORT
# ----------------------------------------------------------------------------------------


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def build_export(session: Session, groups: Iterable[str]) -> tuple[dict, dict]:
    """Baut das Backup-Dokument. Rueckgabe: (Dokument, Zaehler je Abschnitt)."""
    selected = with_dependencies(groups)
    if not selected:
        raise BackupError("Keine gültige Datengruppe für den Export ausgewählt.")

    doc: dict[str, Any] = {}
    counts: dict[str, int] = {}
    new_id = lambda: str(uuid.uuid4())  # noqa: E731

    account_ids: dict[int, str] = {}
    category_ids: dict[int, str] = {}
    transaction_ids: dict[int, str] = {}

    if "accounts" in selected:
        rows = session.exec(select(Account).order_by(Account.id)).all()
        doc["accounts"] = []
        for a in rows:
            account_ids[a.id] = new_id()
            doc["accounts"].append(
                {
                    "export_id": account_ids[a.id],
                    "iban": a.iban,
                    "display_name": a.display_name,
                    "bank_name": a.bank_name,
                    "starting_balance": a.starting_balance,
                    "created_at": _iso(a.created_at),
                }
            )
        counts["accounts"] = len(rows)

    if "categories" in selected:
        rows = session.exec(select(Category).order_by(Category.id)).all()
        for c in rows:
            category_ids[c.id] = new_id()
        doc["categories"] = [
            {
                "export_id": category_ids[c.id],
                "name": c.name,
                "parent": category_ids.get(c.parent_id) if c.parent_id else None,
                "system_key": c.system_key,
                "type": c.type,
            }
            for c in rows
        ]
        counts["categories"] = len(rows)

    if "mapping_profiles" in selected:
        rows = session.exec(select(MappingProfile).order_by(MappingProfile.id)).all()
        doc["mapping_profiles"] = [
            {
                "export_id": new_id(),
                "name": p.name,
                "delimiter": p.delimiter,
                "decimal_separator": p.decimal_separator,
                "encoding": p.encoding,
                "date_format": p.date_format,
                "header_row_index": p.header_row_index,
                "date_column": p.date_column,
                "payee_column": p.payee_column,
                "purpose_column": p.purpose_column,
                "amount_column": p.amount_column,
                "created_at": _iso(p.created_at),
            }
            for p in rows
        ]
        counts["mapping_profiles"] = len(rows)

    if "categorization_rules" in selected:
        # in Prioritaetsreihenfolge (oberste Regel zuerst) - die Reihenfolge der Liste ist die Prioritaet
        rows = [
            r
            for r in session.exec(
                select(CategorizationRule).order_by(CategorizationRule.position, CategorizationRule.id)
            ).all()
            if r.category_id in category_ids
        ]
        doc["categorization_rules"] = [
            {
                "export_id": new_id(),
                "field": r.field,
                "operator": r.operator,
                "value": r.value,
                "mode": r.mode,
                "category": category_ids[r.category_id],
                "created_at": _iso(r.created_at),
            }
            for r in rows
        ]
        counts["categorization_rules"] = len(rows)

    if "budgets" in selected:
        rows = [
            b
            for b in session.exec(select(CategoryBudget).order_by(CategoryBudget.id)).all()
            if b.category_id in category_ids
        ]
        doc["budgets"] = [
            {
                "export_id": new_id(),
                "category": category_ids[b.category_id],
                "monthly_amount": b.monthly_amount,
            }
            for b in rows
        ]
        counts["budgets"] = len(rows)

    if "transactions" in selected:
        rows = session.exec(
            select(Transaction).order_by(Transaction.booking_date, Transaction.id)
        ).all()
        for t in rows:
            transaction_ids[t.id] = new_id()
        doc["transactions"] = [
            {
                "export_id": transaction_ids[t.id],
                "account": account_ids[t.account_id],
                "booking_date": t.booking_date.isoformat(),
                "payee": t.payee,
                "purpose": t.purpose,
                "amount": t.amount,
                "transaction_type": t.transaction_type.value,
                "category": category_ids.get(t.category_id) if t.category_id else None,
                "suggested_category": category_ids.get(t.suggested_category_id) if t.suggested_category_id else None,
                "counter_transaction": transaction_ids.get(t.counter_transaction_id)
                if t.counter_transaction_id
                else None,
                "comment": t.comment,
                "created_at": _iso(t.created_at),
            }
            for t in rows
        ]
        counts["transactions"] = len(rows)

        splits = session.exec(select(TransactionSplit).order_by(TransactionSplit.id)).all()
        doc["transaction_splits"] = [
            {
                "export_id": new_id(),
                "transaction": transaction_ids[s.transaction_id],
                "amount": s.amount,
                "category": category_ids[s.category_id],
                "created_at": _iso(s.created_at),
            }
            for s in splits
            if s.transaction_id in transaction_ids and s.category_id in category_ids
        ]
        counts["transaction_splits"] = len(doc["transaction_splits"])

        pairs = session.exec(select(RejectedTransferPair).order_by(RejectedTransferPair.id)).all()
        doc["rejected_transfer_pairs"] = [
            {
                "export_id": new_id(),
                "transaction_a": transaction_ids[p.transaction_a_id],
                "transaction_b": transaction_ids[p.transaction_b_id],
                "created_at": _iso(p.created_at),
            }
            for p in pairs
            if p.transaction_a_id in transaction_ids and p.transaction_b_id in transaction_ids
        ]
        counts["rejected_transfer_pairs"] = len(doc["rejected_transfer_pairs"])

    meta = {
        "format": BACKUP_FORMAT,
        "schema_version": SCHEMA_VERSION,
        "app_version": app_version(),
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "included_groups": selected,
        "counts": counts,
    }
    return {"meta": meta, **doc}, counts


def dump_json(doc: dict) -> bytes:
    return json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")


def backup_filename(prefix: str = "haushaltsbuch-backup") -> str:
    return f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"


# ----------------------------------------------------------------------------------------
# PARSING / VALIDIERUNG
# ----------------------------------------------------------------------------------------


@dataclass
class Rec:
    index: int
    export_id: Optional[str]
    label: str
    values: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, Optional[str]] = field(default_factory=dict)


@dataclass
class ParsedBackup:
    meta: dict
    records: dict[str, list[Rec]]
    warnings: list[str] = field(default_factory=list)
    problems: dict[str, list[str]] = field(default_factory=dict)

    def present(self, group: str) -> bool:
        return group in self.records

    def counts(self) -> dict[str, int]:
        return {section: len(recs) for section, recs in self.records.items()}

    def status(self, group: str) -> tuple[bool, str]:
        """(importierbar?, Grund falls nicht)."""
        if not self.present(group):
            return False, "In der Datei nicht enthalten."
        if self.problems.get(group):
            return False, "Datei enthält Fehler in diesem Bereich (siehe Fehlerliste)."
        for dep in REQUIRES.get(group, ()):
            ok, why = self.status(dep)
            if not ok:
                return False, f"Benötigt {GROUP_LABELS[dep]}: {why}"
        return True, ""



def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _label(section: str, index: int, values: dict) -> str:
    n = index + 1
    if section == "accounts":
        return f"Konto Nr. {n} ('{values.get('iban', '?')}')"
    if section == "categories":
        return f"Kategorie Nr. {n} ('{values.get('name', '?')}')"
    if section == "mapping_profiles":
        return f"Mapping-Profil Nr. {n} ('{values.get('name', '?')}')"
    if section == "categorization_rules":
        return f"Regel Nr. {n} ('{values.get('value', '?')}')"
    if section == "budgets":
        return f"Budget Nr. {n}"
    if section == "transactions":
        return f"Buchung Nr. {n} ({values.get('booking_date', '?')}, '{values.get('payee', '?')}')"
    if section == "transaction_splits":
        return f"Bargeld-Split Nr. {n}"
    return f"Abgelehnter Vorschlag Nr. {n}"


def _coerce(section: str, name: str, value: Any, label: str, problems: list[str]) -> Any:
    """Wandelt einen Rohwert in den Zieltyp; Fehler landen in problems (Wert dann None)."""
    try:
        if name == "booking_date":
            return date.fromisoformat(str(value))
        if name == "monthly_amount":
            if isinstance(value, bool):
                raise ValueError("kein Zahlenwert")
            amount = float(value)
            if not amount > 0 or amount != amount or amount == float("inf"):
                raise ValueError("muss größer als 0 sein")
            return amount
        if name == "field" and section == "categorization_rules":
            if value not in RULE_FIELDS:
                raise ValueError("erlaubt: " + ", ".join(RULE_FIELDS))
            return value
        if name == "type" and section == "categories":
            if value is None:
                return None
            if value not in CATEGORY_TYPES:
                raise ValueError("erlaubt: " + ", ".join(CATEGORY_TYPES))
            return value
        if name == "mode" and section == "categorization_rules":
            if value not in RULE_MODES:
                raise ValueError("erlaubt: " + ", ".join(RULE_MODES))
            return value
        if name == "operator" and section == "categorization_rules":
            if value not in RULE_OPERATORS:
                raise ValueError("erlaubt: " + ", ".join(RULE_OPERATORS))
            return value
        if name == "value" and section == "categorization_rules":
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Text fehlt")
            return value.strip()
        if name in ("amount", "starting_balance"):
            if value is None:
                return None
            if isinstance(value, bool):
                raise ValueError("kein Zahlenwert")
            return float(value)
        if name == "header_row_index":
            return int(value)
        if name == "created_at":
            return _parse_datetime(value)
        if name == "transaction_type":
            if value is None:
                return None
            text = str(value).strip().lower()
            return TransactionType(text)
        if name == "payee":
            # Auftraggeber/Empfaenger darf leer sein (kommt in echten Bank-CSVs vor, z.B. bei
            # Kartenumsaetzen ohne Gegenpartei) - nur der Typ muss stimmen.
            if not isinstance(value, str):
                raise ValueError("Text erwartet")
            return value
        if name in ("iban", "display_name", "name") or name.endswith("_column"):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Text fehlt")
            return value.strip() if name == "iban" else value
        if value is None:
            return None
        return value if isinstance(value, str) else str(value)
    except (ValueError, TypeError) as exc:
        problems.append(f"{label}: Feld '{name}' hat einen ungültigen Wert ({value!r}): {exc}")
        return None


def parse_backup(raw: bytes) -> ParsedBackup:
    """Liest und validiert ein Backup-Dokument (ohne die DB anzufassen).

    Wirft BackupError bei einer insgesamt unbrauchbaren Datei (kein JSON, falsches Format,
    inkompatible schema_version). Fehler in einzelnen Bereichen landen in
    ``ParsedBackup.problems`` und sperren nur die betroffene Datengruppe.
    """
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupError(f"Die Datei ist kein gültiges JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise BackupError("Die Datei hat nicht das erwartete Backup-Format (Wurzelobjekt fehlt).")
    meta = data.get("meta")
    if not isinstance(meta, dict) or meta.get("format") != BACKUP_FORMAT:
        raise BackupError(
            f"Die Datei ist kein Haushaltsbuch-Backup (Metadaten-Block mit format='{BACKUP_FORMAT}' fehlt)."
        )
    version = meta.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise BackupError("Die Backup-Datei enthält keine gültige schema_version.")
    if version > SCHEMA_VERSION:
        raise BackupError(
            f"Das Backup wurde mit einer neueren Backup-Version (schema_version {version}) erstellt "
            f"als diese App versteht (schema_version {SCHEMA_VERSION}). Bitte die App aktualisieren."
        )
    if version < MIN_SCHEMA_VERSION:
        raise BackupError(
            f"Die schema_version {version} dieses Backups wird nicht mehr unterstützt "
            f"(kleinste unterstützte Version: {MIN_SCHEMA_VERSION})."
        )

    parsed = ParsedBackup(meta=meta, records={})
    problems: dict[str, list[str]] = {g: [] for g in GROUPS}

    # 1) Abschnitte einlesen, Felder pruefen/defaulten
    for section in SECTIONS:
        if section not in data:
            continue
        rows = data[section]
        group = SECTION_GROUP[section]
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            raise BackupError(f"Abschnitt '{section}' hat nicht das erwartete Format (Liste von Objekten).")
        specs = ENTITY_FIELDS[section]
        known = {f.name for f in specs} | {"export_id"} | set(REF_FIELDS.get(section, {}))
        recs: list[Rec] = []
        unknown_seen: dict[str, int] = {}
        missing_seen: dict[str, int] = {}
        for i, row in enumerate(rows):
            label = _label(section, i, row)
            rec = Rec(index=i, export_id=row.get("export_id"), label=label)
            if not isinstance(rec.export_id, str) or not rec.export_id:
                problems[group].append(f"{label}: 'export_id' fehlt.")
                rec.export_id = None
            for key in row:
                if key not in known:
                    unknown_seen[key] = unknown_seen.get(key, 0) + 1
            for f in specs:
                if f.name not in row:
                    if f.required:
                        problems[group].append(f"{label}: Pflichtfeld '{f.name}' fehlt.")
                    elif f.warn_missing:
                        missing_seen[f.name] = missing_seen.get(f.name, 0) + 1
                    rec.values[f.name] = f.default
                    continue
                value = row[f.name]
                if value is None and f.required:
                    problems[group].append(f"{label}: Pflichtfeld '{f.name}' ist leer.")
                    rec.values[f.name] = None
                elif value is None:
                    rec.values[f.name] = f.default
                else:
                    rec.values[f.name] = _coerce(section, f.name, value, label, problems[group])
            for ref_name, (_target, required) in REF_FIELDS.get(section, {}).items():
                ref = row.get(ref_name)
                if ref is None:
                    if required:
                        problems[group].append(f"{label}: Verweis '{ref_name}' fehlt.")
                    rec.refs[ref_name] = None
                elif not isinstance(ref, str):
                    problems[group].append(f"{label}: Verweis '{ref_name}' ist keine Kennung.")
                    rec.refs[ref_name] = None
                else:
                    rec.refs[ref_name] = ref
            # Alte Backups ohne system_key: Systemkategorien anhand des Namens erkennen
            if section == "categories" and "system_key" not in row:
                for key, default_name in SYSTEM_CATEGORY_DEFAULT_NAMES.items():
                    if rec.values.get("name") == default_name:
                        rec.values["system_key"] = key
                        parsed.warnings.append(
                            f"Kategorien: 'system_key' fehlt im Backup - '{default_name}' wurde anhand des Namens "
                            "der Systemkategorie zugeordnet."
                        )
            recs.append(rec)
        label_plural = SECTION_LABELS[section]
        for key, n in sorted(unknown_seen.items()):
            parsed.warnings.append(
                f"{label_plural}: Feld '{key}' existiert im aktuellen Schema nicht und wird ignoriert "
                f"({n} Datensätze)."
            )
        for key, n in sorted(missing_seen.items()):
            default = next(f.default for f in specs if f.name == key)
            shown = "leer" if default is None else repr(default)
            parsed.warnings.append(
                f"{label_plural}: Feld '{key}' fehlt im Backup ({n} von {len(rows)} Datensätzen) - "
                f"Standardwert ({shown}) verwendet."
            )
        parsed.records[section] = recs

    # 2) Grundregel: Buchungen brauchen Konten UND Kategorien, Regeln/Budgets brauchen Kategorien
    #    in derselben Datei
    if "transactions" in parsed.records:
        missing = [
            GROUP_LABELS[g] for g in ("accounts", "categories") if g not in parsed.records
        ]
        if missing:
            problems["transactions"].append(
                "Die Datei enthält Buchungen, aber keine " + " und keine ".join(missing)
                + " - Buchungen können ohne diese Daten nicht importiert werden "
                "(vermutlich mit einer sehr alten Export-Version erstellt)."
            )
    for group in ("categorization_rules", "budgets"):
        if group in parsed.records and "categories" not in parsed.records:
            problems[group].append(
                f"Die Datei enthält {GROUP_LABELS[group]}, aber keine Kategorien - sie können ohne "
                "Kategorien nicht importiert werden."
            )

    # 3) eindeutige export_ids und eindeutige natuerliche Schluessel
    for section, recs in parsed.records.items():
        group = SECTION_GROUP[section]
        seen: set[str] = set()
        for rec in recs:
            if rec.export_id is None:
                continue
            if rec.export_id in seen:
                problems[group].append(f"{rec.label}: 'export_id' {rec.export_id!r} kommt doppelt vor.")
            seen.add(rec.export_id)
    for section, key in (("accounts", "iban"), ("mapping_profiles", "name")):
        seen_values: set[str] = set()
        for rec in parsed.records.get(section, []):
            value = rec.values.get(key)
            if value is None:
                continue
            if value in seen_values:
                problems[SECTION_GROUP[section]].append(
                    f"{rec.label}: {key} '{value}' kommt im Backup mehrfach vor."
                )
            seen_values.add(value)

    seen_budget_categories: set[str] = set()
    for rec in parsed.records.get("budgets", []):
        ref = rec.refs.get("category")
        if ref is None:
            continue
        if ref in seen_budget_categories:
            problems["budgets"].append(f"{rec.label}: für diese Kategorie gibt es im Backup mehrere Budgets.")
        seen_budget_categories.add(ref)

    # 4) Verweise pruefen
    ids = {s: {r.export_id for r in recs if r.export_id} for s, recs in parsed.records.items()}
    for section, ref_fields in REF_FIELDS.items():
        group = SECTION_GROUP[section]
        for rec in parsed.records.get(section, []):
            for ref_name, (target, _required) in ref_fields.items():
                ref = rec.refs.get(ref_name)
                if ref is None:
                    continue
                if target not in parsed.records:
                    continue  # fehlender Ziel-Abschnitt wurde oben bereits gemeldet
                if ref not in ids[target]:
                    problems[group].append(
                        f"{rec.label}: Verweis '{ref_name}' ({ref}) zeigt auf keinen Datensatz in "
                        f"'{target}' - defekte Referenz."
                    )

    # 5) Kategorie-Hierarchie: keine Zyklen
    by_id = {r.export_id: r for r in parsed.records.get("categories", []) if r.export_id}
    for rec in parsed.records.get("categories", []):
        seen_chain: set[str] = set()
        current: Optional[Rec] = rec
        while current is not None and current.refs.get("parent"):
            if current.export_id in seen_chain:
                problems["categories"].append(f"{rec.label}: Die Oberkategorie-Verknüpfung ist zyklisch.")
                break
            seen_chain.add(current.export_id or "")
            current = by_id.get(current.refs["parent"])

    # 6) Abgelehnte Vorschlaege: ein Paar darf nicht aus derselben Buchung bestehen
    for rec in parsed.records.get("rejected_transfer_pairs", []):
        if rec.refs.get("transaction_a") and rec.refs.get("transaction_a") == rec.refs.get("transaction_b"):
            problems["transactions"].append(f"{rec.label}: beide Buchungen des Paars sind identisch.")

    parsed.problems = {g: p for g, p in problems.items() if p}
    return parsed


def resolve_selection(parsed: ParsedBackup, requested: Iterable[str]) -> list[str]:
    """Import-Auswahl validieren und um Abhaengigkeiten ergaenzen."""
    selected = with_dependencies(requested)
    if not selected:
        raise BackupError("Es wurde keine Datengruppe zum Importieren ausgewählt.")
    for group in selected:
        ok, why = parsed.status(group)
        if not ok:
            raise BackupError(f"{GROUP_LABELS[group]} können nicht importiert werden: {why}")
    return selected


# ----------------------------------------------------------------------------------------
# ZIEL-DATENBANK: Zaehler, Ersetzungsplan, Loeschen
# ----------------------------------------------------------------------------------------


def target_counts(session: Session) -> dict[str, int]:
    def count(model, *where) -> int:
        stmt = select(func.count()).select_from(model)
        for clause in where:
            stmt = stmt.where(clause)
        return session.exec(stmt).one()

    return {
        "accounts": count(Account),
        # Systemkategorien zaehlen nicht mit: sie bleiben immer bestehen
        "categories": count(Category, Category.system_key.is_(None)),
        "mapping_profiles": count(MappingProfile),
        "categorization_rules": count(CategorizationRule),
        "budgets": count(CategoryBudget),
        "transactions": count(Transaction),
        "transaction_splits": count(TransactionSplit),
        "rejected_transfer_pairs": count(RejectedTransferPair),
    }


def target_is_empty(counts: dict[str, int]) -> bool:
    return counts["accounts"] == 0 and counts["transactions"] == 0


def replace_plan(selected: Iterable[str], counts: dict[str, int]) -> dict[str, int]:
    """Was der Modus "Bestehende Daten ersetzen" fuer diese Auswahl loeschen wuerde.

    Werden Konten oder Kategorien ersetzt, muessen auch alle bestehenden Buchungen (samt
    Splits/abgelehnten Vorschlaegen) weg - sie wuerden sonst auf geloeschte Datensaetze zeigen;
    ebenso Regeln und Budgets, wenn Kategorien ersetzt werden.
    """
    selected = set(selected)
    plan = {key: 0 for key in counts}
    if "accounts" in selected:
        plan["accounts"] = counts["accounts"]
    if "categories" in selected:
        plan["categories"] = counts["categories"]
    if "mapping_profiles" in selected:
        plan["mapping_profiles"] = counts["mapping_profiles"]
    # Regeln und Budgets zeigen auf Kategorien: werden Kategorien ersetzt, muessen sie mit weg
    if selected & {"categories", "categorization_rules"}:
        plan["categorization_rules"] = counts["categorization_rules"]
    if selected & {"categories", "budgets"}:
        plan["budgets"] = counts["budgets"]
    if selected & {"accounts", "categories", "transactions"}:
        for key in ("transactions", "transaction_splits", "rejected_transfer_pairs"):
            plan[key] = counts[key]
    return plan


def _delete_existing(session: Session, selected: set[str]) -> None:
    if selected & {"accounts", "categories", "transactions"}:
        session.exec(delete(TransactionSplit))
        session.exec(delete(RejectedTransferPair))
        session.exec(delete(Transaction))
    if "accounts" in selected:
        session.exec(delete(Account))
    if "mapping_profiles" in selected:
        session.exec(delete(MappingProfile))
    if selected & {"categories", "categorization_rules"}:
        session.exec(delete(CategorizationRule))
    if selected & {"categories", "budgets"}:
        session.exec(delete(CategoryBudget))
    if "categories" in selected:
        # Systemkategorien bleiben (feste IDs/system_key), nur ihre Oberkategorie wird geloest
        for cat in session.exec(select(Category).where(Category.system_key.is_not(None))).all():
            cat.parent_id = None
            session.add(cat)
        session.flush()
        session.exec(delete(Category).where(Category.system_key.is_(None)))


# ----------------------------------------------------------------------------------------
# IMPORT
# ----------------------------------------------------------------------------------------


@dataclass
class ImportReport:
    mode: str
    selected: list[str]
    skipped: list[str]
    imported: dict[str, int] = field(default_factory=dict)
    deleted: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    safety_backup: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "imported_groups": self.selected,
            "skipped_groups": self.skipped,
            "imported": self.imported,
            "deleted": self.deleted,
            "warnings": self.warnings,
            "safety_backup": self.safety_backup,
        }


def _system_category(session: Session, key: str, name: Optional[str]) -> Category:
    """Systemkategorie zum Schluessel holen/anlegen - OHNE zu committen (Import ist eine
    einzige Transaktion; get_or_create_system_category() wuerde zwischendurch committen)."""
    category = session.exec(select(Category).where(Category.system_key == key)).first()
    if category is None:
        category = session.exec(
            select(Category)
            .where(Category.name == SYSTEM_CATEGORY_DEFAULT_NAMES[key], Category.system_key.is_(None))
            .order_by(Category.id)
        ).first() or Category(name=name or SYSTEM_CATEGORY_DEFAULT_NAMES[key])
        category.system_key = key
        session.add(category)
        session.flush()
    return category


def execute_import(
    session: Session, parsed: ParsedBackup, selected: list[str], mode: str
) -> ImportReport:
    """Fuehrt den Import in EINER Transaktion aus (Commit nur am Ende, sonst Rollback).

    Voraussetzungen (vom Aufrufer geprueft): Auswahl ist gueltig (resolve_selection); bei
    mode="empty" ist das Ziel leer; bei mode="replace" wurde bestaetigt und ein
    Sicherheits-Backup erzeugt.
    """
    selected_set = set(selected)
    report = ImportReport(
        mode=mode,
        selected=selected,
        skipped=[g for g in GROUPS if g not in selected_set],
        warnings=list(parsed.warnings),
    )
    current = "Vorbereitung"
    try:
        if mode == "replace":
            current = "Löschen der bestehenden Daten"
            report.deleted = replace_plan(selected, target_counts(session))
            _delete_existing(session, selected_set)

        accounts: dict[str, Account] = {}
        categories: dict[str, Category] = {}
        transactions: dict[str, Transaction] = {}

        if "accounts" in selected_set:
            current = "Konten"
            for rec in parsed.records["accounts"]:
                v = rec.values
                acc = Account(
                    iban=v["iban"],
                    display_name=v["display_name"],
                    bank_name=v.get("bank_name"),
                    starting_balance=v.get("starting_balance"),
                    created_at=v.get("created_at") or datetime.utcnow(),
                )
                session.add(acc)
                accounts[rec.export_id] = acc
            session.flush()
            report.imported["accounts"] = len(accounts)

        if "categories" in selected_set:
            current = "Kategorien"
            recs = parsed.records["categories"]
            # 1) Systemkategorien -> vorhandene Ziel-Systemkategorien (per system_key, nie neu anlegen)
            normal: list[Rec] = []
            system_recs: list[Rec] = []
            for rec in recs:
                key = rec.values.get("system_key")
                if key in SYSTEM_CATEGORY_DEFAULT_NAMES:
                    categories[rec.export_id] = _system_category(session, key, rec.values.get("name"))
                    system_recs.append(rec)
                else:
                    if key:
                        report.warnings.append(
                            f"Kategorie '{rec.values.get('name')}': unbekannter system_key '{key}' - "
                            "als normale Kategorie importiert."
                        )
                    normal.append(rec)
            # 2) normale Kategorien: Eltern vor Kindern; vorhandene gleichnamige (gleicher Elternteil)
            #    wiederverwenden statt zu duplizieren
            reused = 0
            pending = list(normal)
            while pending:
                progressed = False
                for rec in list(pending):
                    parent_ref = rec.refs.get("parent")
                    if parent_ref is not None and parent_ref not in categories:
                        continue
                    parent_id = categories[parent_ref].id if parent_ref else None
                    name = rec.values["name"]
                    existing = session.exec(
                        select(Category).where(
                            func.lower(Category.name) == name.lower(),
                            Category.parent_id.is_(parent_id) if parent_id is None else Category.parent_id == parent_id,
                            Category.system_key.is_(None),
                        )
                    ).first()
                    if existing is not None:
                        categories[rec.export_id] = existing
                        reused += 1
                    else:
                        # Typ nur an Oberkategorien; fehlt er (aelteres Backup), bestimmt ihn der Abschluss
                        cat = Category(
                            name=name,
                            parent_id=parent_id,
                            type=None if parent_id else rec.values.get("type"),
                        )
                        session.add(cat)
                        session.flush()
                        categories[rec.export_id] = cat
                    pending.remove(rec)
                    progressed = True
                if not progressed:
                    raise ImportFailed("Die Kategorie-Hierarchie im Backup ist nicht auflösbar.")
            # 3) Oberkategorie der Systemkategorien uebernehmen (z.B. "Bargeld" unter einer Oberkategorie)
            for rec in system_recs:
                parent_ref = rec.refs.get("parent")
                if parent_ref and parent_ref in categories:
                    target = categories[rec.export_id]
                    if categories[parent_ref].id != target.id:
                        target.parent_id = categories[parent_ref].id
                        session.add(target)
                # Typ der Systemkategorie (Bargeld); Umbuchung bleibt neutral
                if rec.values.get("system_key") != UMBUCHUNG_KEY and rec.values.get("type"):
                    categories[rec.export_id].type = rec.values["type"]
                    session.add(categories[rec.export_id])
            session.flush()
            report.imported["categories"] = len(recs)
            if reused:
                report.warnings.append(
                    f"Kategorien: {reused} bereits vorhandene Kategorie(n) wiederverwendet (gleicher Name "
                    "und gleiche Oberkategorie) statt sie doppelt anzulegen."
                )

        if "mapping_profiles" in selected_set:
            current = "Mapping-Profile"
            existing_names = set(session.exec(select(MappingProfile.name)).all())
            imported = 0
            for rec in parsed.records["mapping_profiles"]:
                v = rec.values
                if v["name"] in existing_names:
                    report.warnings.append(
                        f"Mapping-Profil '{v['name']}' existiert bereits in der Ziel-Datenbank und wurde "
                        "übersprungen."
                    )
                    continue
                session.add(
                    MappingProfile(
                        name=v["name"],
                        delimiter=v["delimiter"],
                        decimal_separator=v["decimal_separator"],
                        encoding=v["encoding"],
                        date_format=v["date_format"],
                        header_row_index=v["header_row_index"],
                        date_column=v["date_column"],
                        payee_column=v["payee_column"],
                        purpose_column=v["purpose_column"],
                        amount_column=v["amount_column"],
                        created_at=v.get("created_at") or datetime.utcnow(),
                    )
                )
                existing_names.add(v["name"])
                imported += 1
            session.flush()
            report.imported["mapping_profiles"] = imported

        if "categorization_rules" in selected_set:
            current = "Kategorisierungsregeln"
            # hinter bereits vorhandene Regeln anhaengen (im Modus "ersetzen" ist die Liste leer);
            # die Reihenfolge der Datei ist die Prioritaet
            position = session.exec(select(func.max(CategorizationRule.position))).one() or 0
            rule_count = 0
            for rec in parsed.records["categorization_rules"]:
                v = rec.values
                position += 1
                session.add(
                    CategorizationRule(
                        position=position,
                        field=v["field"],
                        operator=v["operator"],
                        value=v["value"],
                        mode=v["mode"],
                        category_id=categories[rec.refs["category"]].id,
                        created_at=v.get("created_at") or datetime.utcnow(),
                    )
                )
                rule_count += 1
            session.flush()
            report.imported["categorization_rules"] = rule_count

        if "budgets" in selected_set:
            current = "Budgets"
            already = set(session.exec(select(CategoryBudget.category_id)).all())
            budget_count = 0
            for rec in parsed.records["budgets"]:
                target = categories[rec.refs["category"]]
                if target.id in already:
                    report.warnings.append(
                        f"Budget für Kategorie '{target.name}' übersprungen: dafür ist bereits ein Budget gesetzt."
                    )
                    continue
                session.add(CategoryBudget(category_id=target.id, monthly_amount=rec.values["monthly_amount"]))
                already.add(target.id)
                budget_count += 1
            session.flush()
            report.imported["budgets"] = budget_count

        if "transactions" in selected_set:
            current = "Buchungen"
            for rec in parsed.records["transactions"]:
                v = rec.values
                kind = v.get("transaction_type") or (
                    TransactionType.EINGANG if v["amount"] > 0 else TransactionType.AUSGANG
                )
                txn = Transaction(
                    account_id=accounts[rec.refs["account"]].id,
                    booking_date=v["booking_date"],
                    payee=v["payee"],
                    purpose=v.get("purpose"),
                    amount=v["amount"],
                    transaction_type=kind,
                    category_id=categories[rec.refs["category"]].id if rec.refs.get("category") else None,
                    suggested_category_id=categories[rec.refs["suggested_category"]].id
                    if rec.refs.get("suggested_category")
                    else None,
                    comment=v.get("comment"),
                    created_at=v.get("created_at") or datetime.utcnow(),
                )
                session.add(txn)
                transactions[rec.export_id] = txn
            session.flush()
            # Umbuchungs-Verknuepfungen erst jetzt (Gegenbuchung braucht eine ID)
            for rec in parsed.records["transactions"]:
                counter_ref = rec.refs.get("counter_transaction")
                if counter_ref:
                    transactions[rec.export_id].counter_transaction_id = transactions[counter_ref].id
            session.flush()
            report.imported["transactions"] = len(transactions)

            current = "Bargeld-Splits"
            split_count = 0
            for rec in parsed.records.get("transaction_splits", []):
                session.add(
                    TransactionSplit(
                        transaction_id=transactions[rec.refs["transaction"]].id,
                        amount=rec.values["amount"],
                        category_id=categories[rec.refs["category"]].id,
                        created_at=rec.values.get("created_at") or datetime.utcnow(),
                    )
                )
                split_count += 1
            report.imported["transaction_splits"] = split_count

            current = "Abgelehnte Umbuchungs-Vorschläge"
            pair_count = 0
            for rec in parsed.records.get("rejected_transfer_pairs", []):
                a_id, b_id = sorted(
                    (transactions[rec.refs["transaction_a"]].id, transactions[rec.refs["transaction_b"]].id)
                )
                session.add(
                    RejectedTransferPair(
                        transaction_a_id=a_id,
                        transaction_b_id=b_id,
                        created_at=rec.values.get("created_at") or datetime.utcnow(),
                    )
                )
                pair_count += 1
            report.imported["rejected_transfer_pairs"] = pair_count

        current = "Abschluss"
        if "categories" in selected_set:
            # Oberkategorien ohne Typ (Backup aus aelterer Version) wie bei der Migration bestimmen
            backfill_category_types(session, commit=False)
        session.commit()
    except ImportFailed:
        session.rollback()
        raise
    except Exception as exc:  # noqa: BLE001 - alles zurueckrollen, verstaendlich melden
        session.rollback()
        raise ImportFailed(
            f"Import abgebrochen und zurückgerollt - Fehler bei '{current}': {exc}. "
            "Es wurden keine Änderungen an der Datenbank vorgenommen."
        ) from exc
    return report


# ----------------------------------------------------------------------------------------
# KOMPLETT-RESET ("Alle Daten loeschen")
# ----------------------------------------------------------------------------------------


def reset_all(session: Session) -> dict[str, int]:
    """Loescht ALLE fachlichen Daten (Konten, Kategorien ausser den Systemkategorien, Mapping-Profile,
    Regeln, Budgets, Buchungen samt Splits/abgelehnten Vorschlaegen) in einer Transaktion.
    Rueckgabe: was geloescht wurde (Zaehler je Abschnitt). Sicherheits-Backup und Bestaetigung sind
    Sache des Aufrufers."""
    deleted = target_counts(session)
    try:
        _delete_existing(session, set(GROUPS))
        session.commit()
    except Exception as exc:  # noqa: BLE001 - zurueckrollen, verstaendlich melden
        session.rollback()
        raise ImportFailed(
            f"Zurücksetzen abgebrochen und zurückgerollt: {exc}. Es wurden keine Daten gelöscht."
        ) from exc
    return deleted
