from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from app.database import get_session
from app.models import Account, Category, Transaction
from app.templating import templates

router = APIRouter(prefix="/transactions", tags=["transactions"])

LIST_LIMIT = 200


def _category_options(session: Session) -> list[dict]:
    top_level = session.exec(
        select(Category).where(Category.parent_id.is_(None)).order_by(Category.name)
    ).all()
    options = []
    for cat in top_level:
        options.append({"id": cat.id, "label": cat.name, "indent": False})
        children = session.exec(
            select(Category).where(Category.parent_id == cat.id).order_by(Category.name)
        ).all()
        for child in children:
            options.append({"id": child.id, "label": child.name, "indent": True})
    return options


def _suggested_category_id(session: Session, txn: Transaction) -> Optional[int]:
    match = session.exec(
        select(Transaction)
        .where(
            Transaction.account_id == txn.account_id,
            Transaction.amount == txn.amount,
            Transaction.payee == txn.payee,
            Transaction.category_id.is_not(None),
            Transaction.id != txn.id,
        )
        .order_by(Transaction.booking_date.desc())
        .limit(1)
    ).first()
    return match.category_id if match else None


def _build_row(
    session: Session, txn: Transaction, accounts_by_id: dict, categories_by_id: dict
) -> dict:
    suggested_id = _suggested_category_id(session, txn) if txn.category_id is None else None
    return {
        "txn": txn,
        "account": accounts_by_id.get(txn.account_id),
        "suggested_category": categories_by_id.get(suggested_id) if suggested_id else None,
    }


def _lookup_dicts(session: Session) -> tuple[dict, dict]:
    accounts_by_id = {a.id: a for a in session.exec(select(Account)).all()}
    categories_by_id = {c.id: c for c in session.exec(select(Category)).all()}
    return accounts_by_id, categories_by_id


@router.get("", response_class=HTMLResponse)
def list_transactions(
    request: Request,
    uncategorized: bool = False,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    query = select(Transaction).order_by(Transaction.booking_date.desc(), Transaction.id.desc())
    if uncategorized:
        query = query.where(Transaction.category_id.is_(None))
    query = query.limit(LIST_LIMIT)
    transactions = session.exec(query).all()

    accounts_by_id, categories_by_id = _lookup_dicts(session)
    rows = [_build_row(session, t, accounts_by_id, categories_by_id) for t in transactions]

    return templates.TemplateResponse(
        request=request,
        name="transactions/list.html",
        context={
            "title": "Buchungen",
            "active_nav": "transactions",
            "rows": rows,
            "category_options": _category_options(session),
            "uncategorized_only": uncategorized,
            "limit": LIST_LIMIT,
        },
    )


@router.post("/{transaction_id}/category", response_class=HTMLResponse)
def set_transaction_category(
    request: Request,
    transaction_id: int,
    category_id: str = Form(""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    txn = session.get(Transaction, transaction_id)
    txn.category_id = int(category_id) if category_id else None
    session.add(txn)
    session.commit()
    session.refresh(txn)

    accounts_by_id, categories_by_id = _lookup_dicts(session)
    row = _build_row(session, txn, accounts_by_id, categories_by_id)

    return templates.TemplateResponse(
        request=request,
        name="transactions/_row.html",
        context={"row": row, "category_options": _category_options(session)},
    )
