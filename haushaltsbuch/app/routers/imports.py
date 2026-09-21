from datetime import date

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from app.database import get_session
from app.models import Account, MappingProfile, Transaction, TransactionType
from app.services.csv_detection import parse_from_header, parse_transaction_rows
from app.services.rules import apply_rule_to_transaction, find_matching_rule, load_rules
from app.templating import templates

router = APIRouter(prefix="/import", tags=["import"])


def _form_context(
    session: Session,
    *,
    form_error: str | None = None,
    selected_account_id: int | None = None,
    selected_profile_id: int | None = None,
) -> dict:
    accounts = session.exec(select(Account).order_by(Account.display_name)).all()
    profiles = session.exec(select(MappingProfile).order_by(MappingProfile.name)).all()
    return {
        "title": "CSV-Import",
        "active_nav": "import",
        "accounts": accounts,
        "profiles": profiles,
        "form_error": form_error,
        "selected_account_id": selected_account_id,
        "selected_profile_id": selected_profile_id,
    }


@router.get("", response_class=HTMLResponse)
def import_form(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="imports/new.html",
        context=_form_context(session),
    )


@router.post("", response_class=HTMLResponse)
async def run_import(
    request: Request,
    account_id: int = Form(...),
    mapping_profile_id: int = Form(...),
    csv_file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    account = session.get(Account, account_id)
    profile = session.get(MappingProfile, mapping_profile_id)

    def _error(message: str, status_code: int = 400) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="imports/new.html",
            context=_form_context(
                session,
                form_error=message,
                selected_account_id=account_id,
                selected_profile_id=mapping_profile_id,
            ),
            status_code=status_code,
        )

    if account is None or profile is None:
        return _error("Bitte ein gültiges Konto und Mapping-Profil auswählen.")

    raw = await csv_file.read()
    if not raw:
        return _error("Die hochgeladene Datei ist leer.")

    header, rows = parse_from_header(
        raw, profile.encoding, profile.delimiter, profile.header_row_index, limit=None
    )

    missing_columns = [
        label
        for col, label in [
            (profile.date_column, "Buchungsdatum"),
            (profile.payee_column, "Auftraggeber/Empfänger"),
            (profile.purpose_column, "Verwendungszweck"),
            (profile.amount_column, "Betrag"),
        ]
        if col not in header
    ]
    if missing_columns:
        return _error(
            "Diese CSV passt nicht zum gewählten Mapping-Profil \""
            + profile.name
            + "\" - Spalten nicht gefunden: "
            + ", ".join(missing_columns)
        )

    parsed_rows = parse_transaction_rows(
        header,
        rows,
        profile.date_format,
        profile.decimal_separator,
        profile.date_column,
        profile.payee_column,
        profile.purpose_column,
        profile.amount_column,
    )

    imported = 0
    auto_categorized = 0  # Regel im Modus "fest zuweisen"
    auto_suggested = 0  # Regel im Modus "nur vorschlagen"
    duplicates: list[dict] = []
    errors: list[dict] = []
    # Regeln (Prioritaetsreihenfolge) einmal laden; sie gelten nur fuer NEU importierte Buchungen -
    # Duplikate werden weiter oben uebersprungen und bestehende Buchungen nie angefasst.
    rules = load_rules(session)

    for index, parsed in enumerate(parsed_rows, start=1):
        if parsed.error:
            errors.append({"row": index, "message": parsed.error})
            continue

        existing = session.exec(
            select(Transaction).where(
                Transaction.account_id == account_id,
                Transaction.booking_date == parsed.booking_date,
                Transaction.amount == parsed.amount,
                Transaction.payee == parsed.payee,
                Transaction.purpose == parsed.purpose,
            )
        ).first()
        if existing:
            duplicates.append(
                {
                    "row": index,
                    "booking_date": parsed.booking_date,
                    "payee": parsed.payee,
                    "purpose": parsed.purpose,
                    "amount": parsed.amount,
                    "existing_transaction_id": existing.id,
                    "existing_created_at": existing.created_at,
                }
            )
            continue

        transaction_type = TransactionType.EINGANG if parsed.amount > 0 else TransactionType.AUSGANG
        new_txn = Transaction(
            account_id=account_id,
            booking_date=parsed.booking_date,
            payee=parsed.payee,
            purpose=parsed.purpose,
            amount=parsed.amount,
            transaction_type=transaction_type,
        )
        rule = find_matching_rule(rules, parsed.payee, parsed.purpose)
        if rule:
            apply_rule_to_transaction(new_txn, rule)
            if rule.mode == "suggest":
                auto_suggested += 1
            else:
                auto_categorized += 1
        session.add(new_txn)
        imported += 1

    session.commit()

    return templates.TemplateResponse(
        request=request,
        name="imports/result.html",
        context={
            "title": "CSV-Import",
            "active_nav": "import",
            "account": account,
            "profile": profile,
            "total_rows": len(parsed_rows),
            "imported": imported,
            "auto_categorized": auto_categorized,
            "auto_suggested": auto_suggested,
            "duplicates": duplicates,
            "errors": errors,
        },
    )


@router.post("/force-import", response_class=HTMLResponse)
async def force_import_duplicates(
    request: Request,
    account_id: int = Form(...),
    all_row: list[int] = Form(default=[]),
    all_date: list[str] = Form(default=[]),
    all_payee: list[str] = Form(default=[]),
    all_purpose: list[str] = Form(default=[]),
    all_amount: list[str] = Form(default=[]),
    selected_rows: list[int] = Form(default=[]),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Importiert vom Nutzer ausgewaehlte, urspruenglich als Duplikat erkannte
    und daher uebersprungene Zeilen nachtraeglich als neue Buchungen - umgeht
    die Duplikat-Erkennung bewusst, da der Nutzer hier explizit bestaetigt,
    dass es sich NICHT um ein Duplikat handelt. Die vier "all_*"-Listen sind
    parallele Arrays (ein Eintrag pro urspruenglich uebersprungener Zeile,
    unabhaengig davon ob ausgewaehlt) - "selected_rows" enthaelt die "row"-
    Werte der tatsaechlich angehakten Zeilen.
    """
    selected = set(selected_rows)
    imported_rows: list[int] = []
    rules = load_rules(session)
    auto_categorized = 0
    auto_suggested = 0
    for row, date_str, payee, purpose, amount_str in zip(
        all_row, all_date, all_payee, all_purpose, all_amount
    ):
        if row not in selected:
            continue
        try:
            booking_date = date.fromisoformat(date_str)
            amount = float(amount_str)
        except ValueError:
            continue
        transaction_type = TransactionType.EINGANG if amount > 0 else TransactionType.AUSGANG
        new_txn = Transaction(
            account_id=account_id,
            booking_date=booking_date,
            payee=payee,
            purpose=purpose or None,
            amount=amount,
            transaction_type=transaction_type,
        )
        rule = find_matching_rule(rules, payee, purpose or None)
        if rule:
            apply_rule_to_transaction(new_txn, rule)
            if rule.mode == "suggest":
                auto_suggested += 1
            else:
                auto_categorized += 1
        session.add(new_txn)
        imported_rows.append(row)
    session.commit()

    count = len(imported_rows)
    message = (
        f"{count} Buchung{'en' if count != 1 else ''} trotzdem importiert."
        + (f" {auto_categorized} davon automatisch kategorisiert." if auto_categorized else "")
        + (f" Für {auto_suggested} liegt ein Kategorie-Vorschlag vor." if auto_suggested else "")
        if count
        else "Keine Zeile ausgewählt."
    )
    banner_class = (
        "alert-error !border-green-200 !bg-green-50 !text-green-700 dark:!border-green-900 "
        "dark:!bg-green-950/40 dark:!text-green-400"
        if count
        else "alert-error !border-gray-200 !bg-gray-50 !text-gray-600 dark:!border-gray-800 "
        "dark:!bg-gray-900 dark:!text-gray-400"
    )
    html = f'<div class="{banner_class}">{message}</div>'
    if imported_rows:
        # Die soeben importierten Zeilen aus der Duplikate-Tabelle entfernen
        # (rein clientseitig - die Ergebnisdaten der urspruenglichen CSV-Import-
        # Antwort werden nicht persistiert, ein Neuladen der ganzen Seite wuerde
        # den urspruenglichen Kontext verlieren).
        html += "<script>(function(){var rows=" + str(imported_rows) + ";rows.forEach(function(r){var tr=document.querySelector('tr[data-dup-row=\"'+r+'\"]');if(tr)tr.remove();});})();</script>"
    return HTMLResponse(content=html)
