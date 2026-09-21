"""Heuristische Analyse einer Beispiel-CSV zur Vorbefüllung eines Mapping-Profils."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date as date_cls
from datetime import datetime
from typing import Optional

from charset_normalizer import from_bytes

# Reale Bank-Exports haben vor der eigentlichen Kopfzeile oft eine
# Metadaten-Präambel (Kontoinhaber, IBAN, Zeitraum, Hinweistexte, ...). Die
# Kopfzeilen-Erkennung sucht innerhalb der ersten RAW_PREVIEW_LINE_LIMIT
# Zeilen (das ist auch das, was dem Nutzer zur manuellen Auswahl angezeigt
# wird); danach werden bis zu SAMPLE_ROW_LIMIT Datenzeilen für die weiteren
# Heuristiken (Dezimaltrennzeichen, Datumsformat) herangezogen.
RAW_PREVIEW_LINE_LIMIT = 20
HEADER_LOOKAHEAD = 5
MIN_HEADER_FIELDS = 4
SAMPLE_ROW_LIMIT = 25
PREVIEW_ROW_LIMIT = 5
_TOTAL_LINE_BUDGET = RAW_PREVIEW_LINE_LIMIT + HEADER_LOOKAHEAD + SAMPLE_ROW_LIMIT

DATE_FORMAT_CANDIDATES = [
    "%d.%m.%Y",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d.%m.%y",
    "%d-%m-%Y",
    "%Y/%m/%d",
]

COLUMN_NAME_HINTS: dict[str, tuple[str, ...]] = {
    "date_column": ("buchungsdatum", "buchungstag", "datum", "date", "valuta"),
    "payee_column": ("auftraggeber", "empfänger", "empfaenger", "begünstigter", "beguenstigter", "name", "payee"),
    "purpose_column": ("verwendungszweck", "zweck", "buchungstext", "purpose", "text", "beschreibung"),
    "amount_column": ("betrag", "amount", "umsatz"),
}

_NUMERIC_RE = re.compile(r"^-?\d[\d.,]*\d$|^-?\d$")


@dataclass
class CsvAnalysis:
    encoding: str
    delimiter: str
    decimal_separator: str
    date_format: str
    header_row_index: int
    raw_preview_lines: list[str]
    header: list[str]
    sample_rows: list[list[str]]
    column_guess: dict[str, Optional[str]]


@dataclass
class PreviewRow:
    booking_date: str
    booking_date_ok: bool
    payee: str
    purpose: str
    amount: str
    amount_ok: bool


@dataclass
class ParsedTransactionRow:
    booking_date: Optional[date_cls]
    payee: str
    purpose: str
    amount: Optional[float]
    error: Optional[str]


def detect_encoding(raw: bytes) -> str:
    if not raw:
        return "utf-8"
    if all(byte < 0x80 for byte in raw):
        # Reines ASCII ist unter UTF-8 und ISO-8859-1/Windows-1252 identisch -
        # charset-normalizer rät hier uneindeutig, UTF-8 ist der sinnvolle Default.
        return "utf-8"
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass

    best = from_bytes(raw).best()
    guess = (best.encoding or "").lower().replace("_", "-") if best else ""
    if "1252" in guess:
        return "windows-1252"
    if "8859" in guess:
        return "iso-8859-1"

    # charset-normalizer ist bei kurzen Samples mit nur vereinzelten High-Bytes
    # (typisch für Bank-CSVs) oft unzuverlässig und rät dann exotische
    # Codepages. Für unseren engen Anwendungsfall (Bank-Export: entweder UTF-8
    # oder eine westeuropäische Kodierung) ist das Vorhandensein von Bytes im
    # Bereich 0x80-0x9F ein zuverlässiges Unterscheidungsmerkmal: dort definiert
    # Windows-1252 druckbare Zeichen (€, „, –, ...), während echtes ISO-8859-1
    # dort nur (in Bank-CSVs praktisch nie genutzte) Steuerzeichen hat.
    if any(0x80 <= byte <= 0x9F for byte in raw):
        return "windows-1252"
    return "iso-8859-1"


def decode(raw: bytes, encoding: str) -> str:
    try:
        return raw.decode(encoding)
    except (LookupError, UnicodeDecodeError):
        return raw.decode("utf-8", errors="replace")


def decode_lines(raw: bytes, encoding: str, limit: int = _TOTAL_LINE_BUDGET) -> list[str]:
    return decode(raw, encoding).splitlines()[:limit]


def detect_delimiter(lines: list[str]) -> str:
    sample = "\n".join(lines)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        return dialect.delimiter
    except csv.Error:
        pass
    # Fallback: über alle Zeilen hinweg das häufigste Kandidaten-Zeichen zählen
    # (robuster als nur die erste Zeile, falls die eine Präambel-Zeile ist).
    counts = {d: sample.count(d) for d in (",", ";", "\t")}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def detect_header_row(
    lines: list[str],
    delimiter: str,
    min_fields: int = MIN_HEADER_FIELDS,
    lookahead: int = HEADER_LOOKAHEAD,
) -> int:
    """Sucht die wahrscheinlichste Kopfzeile innerhalb der Präambel.

    Nimmt die erste Zeile, deren (naive, trennzeichen-basierte) Feldanzahl
    mindestens min_fields beträgt UND mit der Mehrheit der nachfolgenden
    Zeilen übereinstimmt. Naives Split reicht hier: Kopf-/Datenzeilen mit in
    Anführungszeichen stehenden Trennzeichen sind für Bank-CSVs die Ausnahme,
    und diese Heuristik bestimmt nur die Position, nicht die eigentlichen
    Feldwerte.
    """
    search_limit = min(len(lines), RAW_PREVIEW_LINE_LIMIT)
    field_counts = [len(line.split(delimiter)) for line in lines]
    for i in range(search_limit):
        count = field_counts[i]
        if count < min_fields:
            continue
        following = field_counts[i + 1 : i + 1 + lookahead]
        if not following:
            continue
        matches = sum(1 for c in following if c == count)
        if matches >= (len(following) // 2 + 1):
            return i
    return 0


def parse_from_header(
    raw: bytes,
    encoding: str,
    delimiter: str,
    header_row_index: int = 0,
    limit: Optional[int] = None,
) -> tuple[list[str], list[list[str]]]:
    """Parst Header + Datenzeilen ab header_row_index (Präambel wird übersprungen).

    Nutzt csv.reader über den zusammengesetzten Text (nicht zeilenweise), damit
    in Anführungszeichen stehende, mehrzeilige Feldwerte innerhalb der
    Datenzeilen korrekt erkannt werden.
    """
    text = decode(raw, encoding)
    text_lines = text.splitlines()
    if header_row_index >= len(text_lines):
        return [], []
    remaining_text = "\n".join(text_lines[header_row_index:])
    reader = csv.reader(io.StringIO(remaining_text), delimiter=delimiter)
    all_rows = list(reader)
    if not all_rows:
        return [], []
    header = all_rows[0]
    data_rows = [row for row in all_rows[1:] if any(cell.strip() for cell in row)]
    if limit is not None:
        data_rows = data_rows[:limit]
    return header, data_rows


def detect_decimal_separator(rows: list[list[str]]) -> str:
    comma_votes = 0
    dot_votes = 0
    for row in rows:
        for raw_cell in row:
            cell = raw_cell.strip()
            if not cell or not _NUMERIC_RE.match(cell):
                continue
            last_dot = cell.rfind(".")
            last_comma = cell.rfind(",")
            if last_dot == -1 and last_comma == -1:
                continue
            if last_dot > last_comma:
                if 1 <= len(cell[last_dot + 1 :]) <= 2:
                    dot_votes += 1
            elif 1 <= len(cell[last_comma + 1 :]) <= 2:
                comma_votes += 1
    return "," if comma_votes > dot_votes else "."


def _all_match_format(values: list[str], fmt: str) -> bool:
    for value in values:
        try:
            datetime.strptime(value, fmt)
        except ValueError:
            return False
    return True


def detect_date_format(rows: list[list[str]]) -> str:
    if not rows:
        return "%Y-%m-%d"
    num_cols = max((len(row) for row in rows), default=0)
    columns_values = []
    for col in range(num_cols):
        values = [row[col].strip() for row in rows if col < len(row) and row[col].strip()]
        columns_values.append(values)

    for fmt in DATE_FORMAT_CANDIDATES:
        for values in columns_values:
            if values and _all_match_format(values, fmt):
                return fmt
    return "%Y-%m-%d"


def guess_column_mapping(header: list[str]) -> dict[str, Optional[str]]:
    """Ordnet Kopfzeilen-Namen den Zielfeldern per Namens-Heuristik zu.

    Hints werden je Feld in Prioritätsreihenfolge geprüft (erst der
    spezifischste), jeweils über die gesamte Kopfzeile hinweg, bevor auf den
    nächst-generischeren Hint zurückgefallen wird. Das verhindert, dass ein
    generischerer Hint (z.B. "text") eine Spalte matcht, die weiter hinten in
    der Kopfzeile steht, obwohl eine speziellere, korrektere Spalte (z.B.
    "Verwendungszweck" statt "Buchungstext") ebenfalls vorhanden ist.
    """
    guess: dict[str, Optional[str]] = {key: None for key in COLUMN_NAME_HINTS}
    used: set[str] = set()
    for field_key, hints in COLUMN_NAME_HINTS.items():
        for hint in hints:
            if guess[field_key] is not None:
                break
            for col_name in header:
                if col_name in used:
                    continue
                if hint in col_name.strip().lower():
                    guess[field_key] = col_name
                    used.add(col_name)
                    break
    return guess


def analyze(raw: bytes) -> CsvAnalysis:
    encoding = detect_encoding(raw)
    all_lines = decode_lines(raw, encoding)
    raw_preview_lines = all_lines[:RAW_PREVIEW_LINE_LIMIT]

    delimiter = detect_delimiter(all_lines)
    header_row_index = detect_header_row(all_lines, delimiter)

    header, data_rows = parse_from_header(raw, encoding, delimiter, header_row_index, limit=SAMPLE_ROW_LIMIT)
    decimal_separator = detect_decimal_separator(data_rows)
    date_format = detect_date_format(data_rows)
    column_guess = guess_column_mapping(header)

    return CsvAnalysis(
        encoding=encoding,
        delimiter=delimiter,
        decimal_separator=decimal_separator,
        date_format=date_format,
        header_row_index=header_row_index,
        raw_preview_lines=raw_preview_lines,
        header=header,
        sample_rows=data_rows[:PREVIEW_ROW_LIMIT],
        column_guess=column_guess,
    )


def parse_amount(raw_amount: str, decimal_separator: str) -> Optional[float]:
    other_sep = "," if decimal_separator == "." else "."
    normalized = raw_amount.replace(other_sep, "").replace(decimal_separator, ".")
    try:
        return float(normalized)
    except ValueError:
        return None


def reparse_for_preview(
    raw: bytes, encoding: str, delimiter: str, header_row_index: int = 0
) -> tuple[list[str], list[list[str]]]:
    return parse_from_header(raw, encoding, delimiter, header_row_index, limit=PREVIEW_ROW_LIMIT)


def build_preview_rows(
    header: list[str],
    rows: list[list[str]],
    date_format: str,
    decimal_separator: str,
    date_column: Optional[str],
    payee_column: Optional[str],
    purpose_column: Optional[str],
    amount_column: Optional[str],
) -> list[PreviewRow]:
    def col_index(name: Optional[str]) -> Optional[int]:
        if not name:
            return None
        try:
            return header.index(name)
        except ValueError:
            return None

    date_idx = col_index(date_column)
    payee_idx = col_index(payee_column)
    purpose_idx = col_index(purpose_column)
    amount_idx = col_index(amount_column)

    def cell(row: list[str], idx: Optional[int]) -> str:
        if idx is None or idx >= len(row):
            return ""
        return row[idx].strip()

    result: list[PreviewRow] = []
    for row in rows:
        raw_date = cell(row, date_idx)
        booking_date_ok = True
        display_date = raw_date
        if raw_date:
            try:
                display_date = datetime.strptime(raw_date, date_format).date().isoformat()
            except ValueError:
                booking_date_ok = False
        elif date_idx is not None:
            booking_date_ok = False

        raw_amount = cell(row, amount_idx)
        amount_ok = True
        display_amount = raw_amount
        if raw_amount:
            parsed_amount = parse_amount(raw_amount, decimal_separator)
            if parsed_amount is None:
                amount_ok = False
            else:
                display_amount = f"{parsed_amount:.2f}"
        elif amount_idx is not None:
            amount_ok = False

        result.append(
            PreviewRow(
                booking_date=display_date,
                booking_date_ok=booking_date_ok,
                payee=cell(row, payee_idx),
                purpose=cell(row, purpose_idx),
                amount=display_amount,
                amount_ok=amount_ok,
            )
        )
    return result


def parse_transaction_rows(
    header: list[str],
    rows: list[list[str]],
    date_format: str,
    decimal_separator: str,
    date_column: str,
    payee_column: str,
    purpose_column: str,
    amount_column: str,
) -> list[ParsedTransactionRow]:
    """Parst Datenzeilen für den eigentlichen CSV-Import (typisierte Werte statt Anzeige-Strings)."""

    def col_index(name: str) -> Optional[int]:
        try:
            return header.index(name)
        except ValueError:
            return None

    date_idx = col_index(date_column)
    payee_idx = col_index(payee_column)
    purpose_idx = col_index(purpose_column)
    amount_idx = col_index(amount_column)

    def cell(row: list[str], idx: Optional[int]) -> str:
        if idx is None or idx >= len(row):
            return ""
        return row[idx].strip()

    result: list[ParsedTransactionRow] = []
    for row in rows:
        raw_date = cell(row, date_idx)
        raw_amount = cell(row, amount_idx)
        payee = cell(row, payee_idx)
        purpose = cell(row, purpose_idx)

        booking_date: Optional[date_cls] = None
        amount: Optional[float] = None
        error: Optional[str] = None

        try:
            booking_date = datetime.strptime(raw_date, date_format).date()
        except ValueError:
            error = f"Buchungsdatum \"{raw_date}\" passt nicht zum Format {date_format}."

        if error is None:
            amount = parse_amount(raw_amount, decimal_separator)
            if amount is None:
                error = f"Betrag \"{raw_amount}\" konnte nicht gelesen werden."

        result.append(
            ParsedTransactionRow(
                booking_date=booking_date,
                payee=payee,
                purpose=purpose,
                amount=amount,
                error=error,
            )
        )
    return result
