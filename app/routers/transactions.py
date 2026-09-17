from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from app.database import get_session
from app.models import Account, Category, Transaction, TransactionType
from app.templating import templates

router = APIRouter(prefix="/transactions", tags=["transactions"])

LIST_LIMIT = 200
TRANSFER_WINDOW_DAYS = 2


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


def _transfer_candidates(session: Session, txn: Transaction) -> list[Transaction]:
    """Sucht mögliche Umbuchungs-Gegenbuchungen: anderes Konto, exakt gegenteiliger
    Betrag, Buchungsdatum innerhalb von ±TRANSFER_WINDOW_DAYS, noch nicht verknüpft.
    """
    if txn.counter_transaction_id is not None:
        return []
    window_start = txn.booking_date - timedelta(days=TRANSFER_WINDOW_DAYS)
    window_end = txn.booking_date + timedelta(days=TRANSFER_WINDOW_DAYS)
    candidates = session.exec(
        select(Transaction).where(
            Transaction.id != txn.id,
            Transaction.account_id != txn.account_id,
            Transaction.amount == -txn.amount,
            Transaction.booking_date >= window_start,
            Transaction.booking_date <= window_end,
            Transaction.counter_transaction_id.is_(None),
        )
    ).all()
    # Manuell markierte Umbuchungen zuerst anzeigen (vorausgewählter Treffer lt. Spec).
    candidates.sort(key=lambda c: 0 if c.transaction_type == TransactionType.UMBUCHUNG else 1)
    return candidates


def _toggle_url(uncategorized: bool, hide_transfers: bool, toggle: str) -> str:
    if toggle == "uncategorized":
        uncategorized = not uncategorized
    else:
        hide_transfers = not hide_transfers
    params = []
    if uncategorized:
        params.append("uncategorized=1")
    if hide_transfers:
        params.append("hide_transfers=1")
    return "/transactions" + ("?" + "&".join(params) if params else "")


def _lookup_dicts(session: Session) -> tuple[dict, dict]:
    accounts_by_id = {a.id: a for a in session.exec(select(Account)).all()}
    categories_by_id = {c.id: c for c in session.exec(select(Category)).all()}
    return accounts_by_id, categories_by_id


def _build_row(
    session: Session, txn: Transaction, accounts_by_id: dict, categories_by_id: dict
) -> dict:
    suggested_id = _suggested_category_id(session, txn) if txn.category_id is None else None

    counter_txn = None
    counter_account = None
    if txn.counter_transaction_id:
        counter_txn = session.get(Transaction, txn.counter_transaction_id)
        if counter_txn:
            counter_account = accounts_by_id.get(counter_txn.account_id)

    transfer_candidates = [
        {"txn": c, "account": accounts_by_id.get(c.account_id)}
        for c in _transfer_candidates(session, txn)
    ]

    return {
        "txn": txn,
        "account": accounts_by_id.get(txn.account_id),
        "suggested_category": categories_by_id.get(suggested_id) if suggested_id else None,
        "counter_txn": counter_txn,
        "counter_account": counter_account,
        "transfer_candidates": transfer_candidates,
    }


def _render_row_html(session: Session, txn: Transaction, oob: bool) -> str:
    accounts_by_id, categories_by_id = _lookup_dicts(session)
    row = _build_row(session, txn, accounts_by_id, categories_by_id)
    template = templates.env.get_template("transactions/_row.html")
    return template.render(row=row, category_options=_category_options(session), oob=oob)


@router.get("", response_class=HTMLResponse)
def list_transactions(
    request: Request,
    uncategorized: bool = False,
    hide_transfers: bool = False,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    query = select(Transaction).order_by(Transaction.booking_date.desc(), Transaction.id.desc())
    if uncategorized:
        query = query.where(Transaction.category_id.is_(None))
    if hide_transfers:
        query = query.where(Transaction.transaction_type != TransactionType.UMBUCHUNG)
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
            "hide_transfers": hide_transfers,
            "toggle_uncategorized_url": _toggle_url(uncategorized, hide_transfers, "uncategorized"),
            "toggle_hide_transfers_url": _toggle_url(uncategorized, hide_transfers, "hide_transfers"),
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
    return HTMLResponse(content=_render_row_html(session, txn, oob=False))


@router.post("/{transaction_id}/mark-transfer", response_class=HTMLResponse)
def mark_as_transfer(
    request: Request, transaction_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    txn = session.get(Transaction, transaction_id)
    if txn.counter_transaction_id is None:
        txn.transaction_type = TransactionType.UMBUCHUNG
        session.add(txn)
        session.commit()
        session.refresh(txn)
    return HTMLResponse(content=_render_row_html(session, txn, oob=False))


@router.post("/{transaction_id}/unmark-transfer", response_class=HTMLResponse)
def unmark_transfer(
    request: Request, transaction_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    txn = session.get(Transaction, transaction_id)
    if txn.counter_transaction_id is None:
        txn.transaction_type = TransactionType.EINGANG if txn.amount > 0 else TransactionType.AUSGANG
        session.add(txn)
        session.commit()
        session.refresh(txn)
    return HTMLResponse(content=_render_row_html(session, txn, oob=False))


@router.post("/{transaction_id}/confirm-transfer", response_class=HTMLResponse)
def confirm_transfer(
    request: Request,
    transaction_id: int,
    counter_transaction_id: int = Form(...),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    txn = session.get(Transaction, transaction_id)
    counter = session.get(Transaction, counter_transaction_id)

    if (
        txn is not None
        and counter is not None
        and txn.counter_transaction_id is None
        and counter.counter_transaction_id is None
        and txn.id != counter.id
    ):
        txn.counter_transaction_id = counter.id
        txn.transaction_type = TransactionType.UMBUCHUNG
        counter.counter_transaction_id = txn.id
        counter.transaction_type = TransactionType.UMBUCHUNG
        session.add(txn)
        session.add(counter)
        session.commit()
        session.refresh(txn)
        session.refresh(counter)

    html = _render_row_html(session, txn, oob=False)
    if counter is not None:
        html += _render_row_html(session, counter, oob=True)
    return HTMLResponse(content=html)


@router.post("/{transaction_id}/unlink-transfer", response_class=HTMLResponse)
def unlink_transfer(
    request: Request, transaction_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    txn = session.get(Transaction, transaction_id)
    counter = session.get(Transaction, txn.counter_transaction_id) if txn.counter_transaction_id else None

    txn.counter_transaction_id = None
    txn.transaction_type = TransactionType.EINGANG if txn.amount > 0 else TransactionType.AUSGANG
    session.add(txn)
    if counter is not None:
        counter.counter_transaction_id = None
        counter.transaction_type = TransactionType.EINGANG if counter.amount > 0 else TransactionType.AUSGANG
        session.add(counter)
    session.commit()
    session.refresh(txn)

    html = _render_row_html(session, txn, oob=False)
    if counter is not None:
        session.refresh(counter)
        html += _render_row_html(session, counter, oob=True)
    return HTMLResponse(content=html)
