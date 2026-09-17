from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from app.database import get_session
from app.models import Account, MappingProfile, Transaction, TransactionType
from app.services.csv_detection import parse_from_header, parse_transaction_rows
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
    duplicates: list[dict] = []
    errors: list[dict] = []

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
        session.add(
            Transaction(
                account_id=account_id,
                booking_date=parsed.booking_date,
                payee=parsed.payee,
                purpose=parsed.purpose,
                amount=parsed.amount,
                transaction_type=transaction_type,
            )
        )
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
            "duplicates": duplicates,
            "errors": errors,
        },
    )
