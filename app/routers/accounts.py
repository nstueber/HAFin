from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.database import get_session
from app.models import Account, Transaction

router = APIRouter(prefix="/accounts", tags=["accounts"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")


def _normalize_iban(iban: str) -> str:
    return iban.replace(" ", "").upper().strip()


@router.get("", response_class=HTMLResponse)
def list_accounts(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    accounts = session.exec(select(Account).order_by(Account.display_name)).all()
    return templates.TemplateResponse(
        request=request,
        name="accounts/list.html",
        context={"title": "Konten", "active_nav": "accounts", "accounts": accounts},
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
        context={"title": "Konto bearbeiten", "active_nav": "accounts", "account": account},
    )


@router.post("/{account_id}/edit", response_class=HTMLResponse)
def update_account(
    request: Request,
    account_id: int,
    iban: str = Form(...),
    display_name: str = Form(...),
    bank_name: str = Form(""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    account = session.get(Account, account_id)
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
    session.delete(account)
    session.commit()
    return HTMLResponse(content="")
