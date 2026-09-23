"""Unit-Tests fuer app/services/csv_detection.py (Encoding/Trennzeichen/Format-Heuristiken)."""

from app.services import csv_detection as svc


# ------------------------------------------------------------------------------ detect_encoding


def test_detect_encoding_pure_ascii_is_utf8():
    assert svc.detect_encoding(b"Datum;Betrag\n01.01.2026;-10,00\n") == "utf-8"


def test_detect_encoding_valid_utf8_with_umlauts():
    raw = "Auftraggeber;Zweck\nMüller & Söhne;Überweisung".encode("utf-8")
    assert svc.detect_encoding(raw) == "utf-8"


def test_detect_encoding_windows_1252_euro_sign():
    # Byte 0x80 ist in windows-1252 "€"; in echtem ISO-8859-1 dort nur ein Steuerzeichen (siehe
    # Kommentar im Quellcode) - genau das Unterscheidungsmerkmal, das hier geprueft wird. Als
    # rohes Byte-Literal, nicht ueber .encode("windows-1252") (das lehnt den Unicode-Codepoint
    # U+0080 als "nicht abbildbar" ab - hier geht es um das BYTE 0x80, nicht das Zeichen U+0080).
    raw = b"Betrag: 10\x80 EUR"
    assert svc.detect_encoding(raw) == "windows-1252"


def test_detect_encoding_empty_bytes_is_utf8():
    assert svc.detect_encoding(b"") == "utf-8"


# ----------------------------------------------------------------------------- detect_delimiter


def test_detect_delimiter_semicolon():
    lines = ["Datum;Auftraggeber;Betrag", "01.01.2026;REWE;-10,00"]
    assert svc.detect_delimiter(lines) == ";"


def test_detect_delimiter_comma():
    lines = ["Date,Payee,Amount", "2026-01-01,REWE,-10.00"]
    assert svc.detect_delimiter(lines) == ","


# --------------------------------------------------------------------------- detect_header_row


def test_detect_header_row_skips_preamble():
    lines = [
        "Kontoauszug für Konto DE00",
        "Zeitraum: 01.01.2026 - 31.01.2026",
        "",
        "Datum;Auftraggeber;Verwendungszweck;Betrag",
        "01.01.2026;REWE;Einkauf;-10,00",
        "02.01.2026;ALDI;Einkauf;-5,00",
        "03.01.2026;Kino;Film;-8,00",
    ]
    assert svc.detect_header_row(lines, ";") == 3


def test_detect_header_row_no_preamble_returns_zero():
    lines = ["Datum;Betrag", "01.01.2026;-10,00", "02.01.2026;-5,00", "03.01.2026;-3,00"]
    assert svc.detect_header_row(lines, ";") == 0


# ----------------------------------------------------------------------- detect_decimal_separator


def test_detect_decimal_separator_german_comma():
    rows = [["01.01.2026", "REWE", "-10,00"], ["02.01.2026", "ALDI", "-5,50"]]
    assert svc.detect_decimal_separator(rows) == ","


def test_detect_decimal_separator_dot_with_thousands_comma():
    rows = [["2026-01-01", "REWE", "-1,234.56"], ["2026-01-02", "ALDI", "-5.50"]]
    assert svc.detect_decimal_separator(rows) == "."


def test_detect_decimal_separator_no_numeric_cells_defaults_to_dot():
    assert svc.detect_decimal_separator([["a", "b"], ["c", "d"]]) == "."


# --------------------------------------------------------------------------- detect_date_format


def test_detect_date_format_german():
    rows = [["01.01.2026", "-10,00"], ["15.03.2026", "-5,00"]]
    assert svc.detect_date_format(rows) == "%d.%m.%Y"


def test_detect_date_format_iso():
    rows = [["2026-01-01", "-10.00"], ["2026-03-15", "-5.00"]]
    assert svc.detect_date_format(rows) == "%Y-%m-%d"


def test_detect_date_format_empty_rows_defaults_to_iso():
    assert svc.detect_date_format([]) == "%Y-%m-%d"


# ------------------------------------------------------------------------ guess_column_mapping


def test_guess_column_mapping_german_bank_headers():
    header = ["Buchungstag", "Beguenstigter/Zahlungspflichtiger", "Verwendungszweck", "Betrag"]
    guess = svc.guess_column_mapping(header)
    assert guess == {
        "date_column": "Buchungstag",
        "payee_column": "Beguenstigter/Zahlungspflichtiger",
        "purpose_column": "Verwendungszweck",
        "amount_column": "Betrag",
    }


def test_guess_column_mapping_prefers_specific_hint_over_generic():
    # "Verwendungszweck" (spezifischer Hint) UND "Buchungstext" (generischerer Hint fuer denselben
    # Zielfeld-Typ) sind beide vorhanden - der spezifischere Name muss gewinnen, nicht der erste
    # in der Kopfzeile.
    header = ["Buchungstext", "Datum", "Verwendungszweck", "Betrag"]
    guess = svc.guess_column_mapping(header)
    assert guess["purpose_column"] == "Verwendungszweck"


def test_guess_column_mapping_no_match_is_none():
    assert svc.guess_column_mapping(["Spalte A", "Spalte B"]) == {
        "date_column": None, "payee_column": None, "purpose_column": None, "amount_column": None,
    }


# --------------------------------------------------------------------------------- parse_amount


def test_parse_amount_comma_decimal():
    assert svc.parse_amount("-1.234,56", ",") == -1234.56


def test_parse_amount_dot_decimal():
    assert svc.parse_amount("-1,234.56", ".") == -1234.56


def test_parse_amount_invalid_returns_none():
    assert svc.parse_amount("nicht-numerisch", ",") is None


# -------------------------------------------------------------------------------------- analyze


def test_analyze_full_pipeline_with_preamble():
    csv_bytes = (
        "Kontoauszug\r\n"
        "IBAN: DE00 1234 5678\r\n"
        "\r\n"
        "Buchungstag;Beguenstigter/Zahlungspflichtiger;Verwendungszweck;Betrag\r\n"
        "01.09.2026;REWE Markt;Einkauf;-45,30\r\n"
        "02.09.2026;Arbeitgeber GmbH;Gehalt;2.500,00\r\n"
    ).encode("utf-8")

    result = svc.analyze(csv_bytes)

    assert result.encoding == "utf-8"
    assert result.delimiter == ";"
    assert result.header_row_index == 3
    assert result.header == ["Buchungstag", "Beguenstigter/Zahlungspflichtiger", "Verwendungszweck", "Betrag"]
    assert result.decimal_separator == ","
    assert result.date_format == "%d.%m.%Y"
    assert result.column_guess["amount_column"] == "Betrag"
    assert len(result.sample_rows) == 2


# ------------------------------------------------------------------------- parse_transaction_rows


def test_parse_transaction_rows_valid_and_invalid():
    header = ["Datum", "Auftraggeber", "Zweck", "Betrag"]
    rows = [
        ["01.09.2026", "REWE", "Einkauf", "-45,30"],
        ["nicht-ein-datum", "ALDI", "Einkauf", "-5,00"],
        ["03.09.2026", "Kino", "Film", "nicht-numerisch"],
    ]
    parsed = svc.parse_transaction_rows(header, rows, "%d.%m.%Y", ",", "Datum", "Auftraggeber", "Zweck", "Betrag")

    assert len(parsed) == 3
    assert parsed[0].error is None
    assert parsed[0].amount == -45.30
    assert parsed[0].booking_date.isoformat() == "2026-09-01"
    assert parsed[1].error is not None and "Buchungsdatum" in parsed[1].error
    assert parsed[2].error is not None and "Betrag" in parsed[2].error
