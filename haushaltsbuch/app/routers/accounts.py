import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from sqlmodel import Session as _Session

from app.database import engine, get_session
from app.models import Account, MappingProfile, RecurringIgnore, Transaction
from app.services.import_history import backfill_default_mapping_profiles
from app.templating import templates

router = APIRouter(prefix="/accounts", tags=["accounts"])


def backfill_mapping_profiles() -> None:
    """Einmalige Migration der Standard-Mapping-Profile je Konto (siehe import_history-Service)."""
    with _Session(engine) as session:
        backfill_default_mapping_profiles(session)


def _profiles(session: Session) -> list[MappingProfile]:
    return list(session.exec(select(MappingProfile).order_by(MappingProfile.name)).all())


def _valid_profile_id(session: Session, raw: str) -> int | None:
    """Formularwert -> ID eines existierenden Mapping-Profils, sonst None (leer = kein Standard)."""
    if raw.isdigit() and session.get(MappingProfile, int(raw)) is not None:
        return int(raw)
    return None


def _normalize_iban(iban: str) -> str:
    return re.sub(r"\s+", "", iban).upper()


@router.get("", response_class=HTMLResponse)
def list_accounts(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    accounts = session.exec(select(Account).order_by(Account.display_name)).all()
    return templates.TemplateResponse(
        request=request,
        name="accounts/list.html",
        context={
            "title": "Konten",
            "active_nav": "accounts",
            "accounts": accounts,
            "profile_names": {p.id: p.name for p in _profiles(session)},
        },
    )


@router.post("", response_class=HTMLResponse)
def create_account(
    request: Request,
    iban: str = Form(...),
    display_name: str = Form(...),
    bank_name: str = Form(""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    account = Account(
        iban=_normalize_iban(iban),
        display_name=display_name.strip(),
        bank_name=bank_name.strip() or None,
    )
    session.add(account)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        accounts = session.exec(select(Account).order_by(Account.display_name)).all()
        return templates.TemplateResponse(
            request=request,
            name="accounts/list.html",
            context={
                "title": "Konten",
                "active_nav": "accounts",
                "accounts": accounts,
                "profile_names": {p.id: p.name for p in _profiles(session)},
                "form_error": f"Ein Konto mit IBAN {_normalize_iban(iban)} existiert bereits.",
                "form_data": {"iban": iban, "display_name": display_name, "bank_name": bank_name},
            },
            status_code=400,
        )
    return RedirectResponse(url="/accounts", status_code=303)


@router.get("/{account_id}/edit", response_class=HTMLResponse)
def edit_account_form(
    request: Request, account_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    account = session.get(Account, account_id)
    return templates.TemplateResponse(
        request=request,
        name="accounts/edit.html",
        context={
            "title": "Konto bearbeiten",
            "active_nav": "accounts",
            "account": account,
            "profiles": _profiles(session),
        },
    )


@router.post("/{account_id}/edit", response_class=HTMLResponse)
def update_account(
    request: Request,
    account_id: int,
    iban: str = Form(...),
    display_name: str = Form(...),
    bank_name: str = Form(""),
    default_mapping_profile_id: str = Form(""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    account = session.get(Account, account_id)
    account.default_mapping_profile_id = _valid_profile_id(session, default_mapping_profile_id)
    account.iban = _normalize_iban(iban)
    account.display_name = display_name.strip()
    account.bank_name = bank_name.strip() or None
    session.add(account)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return templates.TemplateResponse(
            request=request,
            name="accounts/edit.html",
            context={
                "title": "Konto bearbeiten",
                "active_nav": "accounts",
                "account": account,
                "profiles": _profiles(session),
                "form_error": f"Ein Konto mit IBAN {_normalize_iban(iban)} existiert bereits.",
            },
            status_code=400,
        )
    return RedirectResponse(url="/accounts", status_code=303)


@router.post("/{account_id}/delete", response_class=HTMLResponse)
def delete_account(
    request: Request, account_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    account = session.get(Account, account_id)
    has_transactions = session.exec(
        select(Transaction).where(Transaction.account_id == account_id).limit(1)
    ).first()
    if has_transactions:
        return templates.TemplateResponse(
            request=request,
            name="accounts/_row_error.html",
            context={
                "account": account,
                "error": "Konto hat bereits Transaktionen und kann nicht gelöscht werden.",
            },
            status_code=409,
        )
    for ignore in session.exec(select(RecurringIgnore).where(RecurringIgnore.account_id == account_id)).all():
        session.delete(ignore)
    session.delete(account)
    session.commit()
    return HTMLResponse(content="")
