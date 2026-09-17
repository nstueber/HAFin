from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from app.database import get_session
from app.models import Account, Category, RejectedTransferPair, Transaction, TransactionType
from app.templating import templates

router = APIRouter(prefix="/transactions", tags=["transactions"])

LIST_LIMIT = 200
TRANSFER_WINDOW_DAYS = 2
SUGGESTIONS_LIMIT = 20
UMBUCHUNG_CATEGORY_NAME = "Umbuchung"


def _category_groups(session: Session) -> list[dict]:
    """Kategorien gruppiert für die Dropdown-Darstellung (Optgroups je Oberkategorie)."""
    top_level = session.exec(
        select(Category).where(Category.parent_id.is_(None)).order_by(Category.name)
    ).all()
    groups = []
    for cat in top_level:
        children = session.exec(
            select(Category).where(Category.parent_id == cat.id).order_by(Category.name)
        ).all()
        groups.append(
            {
                "id": cat.id,
                "name": cat.name,
                "children": [{"id": c.id, "name": c.name} for c in children],
            }
        )
    return groups


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


def _get_or_create_umbuchung_category(session: Session) -> Category:
    category = session.exec(
        select(Category).where(Category.name == UMBUCHUNG_CATEGORY_NAME)
    ).first()
    if category is None:
        category = Category(name=UMBUCHUNG_CATEGORY_NAME)
        session.add(category)
        session.commit()
        session.refresh(category)
    return category


def _load_rejected_pairs(session: Session) -> set:
    rows = session.exec(select(RejectedTransferPair)).all()
    return {frozenset({r.transaction_a_id, r.transaction_b_id}) for r in rows}


def _transfer_candidates(
    session: Session, txn: Transaction, rejected_pairs: set
) -> list[Transaction]:
    """Sucht mögliche Umbuchungs-Gegenbuchungen: anderes Konto, exakt gegenteiliger
    Betrag, Buchungsdatum innerhalb von ±TRANSFER_WINDOW_DAYS, noch nicht verknüpft
    und nicht bereits von Hand als "keine Umbuchung" abgelehnt.
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
    candidates = [
        c for c in candidates if frozenset({txn.id, c.id}) not in rejected_pairs
    ]
    # Manuell markierte Umbuchungen zuerst anzeigen (vorausgewählter Treffer lt. Spec).
    candidates.sort(key=lambda c: 0 if c.transaction_type == TransactionType.UMBUCHUNG else 1)
    return candidates


def _pending_transfer_suggestions(
    session: Session, accounts_by_id: dict, rejected_pairs: set
) -> list[dict]:
    """Alle aktuell unverknüpften Umbuchungs-Treffer, kontoübergreifend und dedupliziert.

    Unabhängig von der 200-Zeilen-Begrenzung der Hauptliste, damit ein Treffer nicht
    übersehen wird, nur weil eine der beiden Seiten außerhalb der neuesten 200
    Buchungen liegt.
    """
    unlinked = session.exec(
        select(Transaction).where(Transaction.counter_transaction_id.is_(None))
    ).all()
    seen_pairs: set = set()
    suggestions = []
    for txn in unlinked:
        for cand in _transfer_candidates(session, txn, rejected_pairs):
            pair_key = frozenset({txn.id, cand.id})
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            suggestions.append(
                {
                    "a": txn,
                    "a_account": accounts_by_id.get(txn.account_id),
                    "b": cand,
                    "b_account": accounts_by_id.get(cand.account_id),
                }
            )
    return suggestions


def _manual_link_candidates(session: Session, txn: Transaction) -> list[Transaction]:
    """Kandidaten für die manuelle Verknüpfung: unverknüpfte Buchungen anderer Konten
    mit exakt entgegengesetztem Betrag (andere Beträge werden nicht angeboten),
    nach zeitlicher Nähe sortiert.
    """
    if txn.counter_transaction_id is not None:
        return []
    candidates = session.exec(
        select(Transaction).where(
            Transaction.id != txn.id,
            Transaction.account_id != txn.account_id,
            Transaction.amount == -txn.amount,
            Transaction.counter_transaction_id.is_(None),
        )
    ).all()
    candidates.sort(key=lambda c: abs((c.booking_date - txn.booking_date).days))
    return candidates


def _link_transactions(
    session: Session, transaction_id: int, counter_transaction_id: int
) -> tuple[Optional[Transaction], Optional[Transaction]]:
    txn = session.get(Transaction, transaction_id)
    counter = session.get(Transaction, counter_transaction_id)

    if (
        txn is not None
        and counter is not None
        and txn.counter_transaction_id is None
        and counter.counter_transaction_id is None
        and txn.id != counter.id
        and txn.account_id != counter.account_id
        and txn.amount == -counter.amount
    ):
        umbuchung_category = _get_or_create_umbuchung_category(session)
        txn.counter_transaction_id = counter.id
        txn.transaction_type = TransactionType.UMBUCHUNG
        txn.category_id = umbuchung_category.id
        counter.counter_transaction_id = txn.id
        counter.transaction_type = TransactionType.UMBUCHUNG
        counter.category_id = umbuchung_category.id
        session.add(txn)
        session.add(counter)
        session.commit()
        session.refresh(txn)
        session.refresh(counter)

    return txn, counter


def _reject_suggestion(session: Session, transaction_id: int, counter_transaction_id: int) -> None:
    a_id, b_id = sorted((transaction_id, counter_transaction_id))
    exists = session.exec(
        select(RejectedTransferPair).where(
            RejectedTransferPair.transaction_a_id == a_id,
            RejectedTransferPair.transaction_b_id == b_id,
        )
    ).first()
    if exists is None:
        session.add(RejectedTransferPair(transaction_a_id=a_id, transaction_b_id=b_id))
        session.commit()


def _filter_url(uncategorized: bool, transfers: str) -> str:
    params = []
    if uncategorized:
        params.append("uncategorized=1")
    if transfers != "all":
        params.append(f"transfers={transfers}")
    return "/transactions" + ("?" + "&".join(params) if params else "")


def _lookup_dicts(session: Session) -> tuple[dict, dict]:
    accounts_by_id = {a.id: a for a in session.exec(select(Account)).all()}
    categories_by_id = {c.id: c for c in session.exec(select(Category)).all()}
    return accounts_by_id, categories_by_id


def _build_row(
    session: Session,
    txn: Transaction,
    accounts_by_id: dict,
    categories_by_id: dict,
    rejected_pairs: set,
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
        for c in _transfer_candidates(session, txn, rejected_pairs)
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
    rejected_pairs = _load_rejected_pairs(session)
    row = _build_row(session, txn, accounts_by_id, categories_by_id, rejected_pairs)
    template = templates.env.get_template("transactions/_row.html")
    return template.render(row=row, category_groups=_category_groups(session), oob=oob)


@router.get("", response_class=HTMLResponse)
def list_transactions(
    request: Request,
    uncategorized: bool = False,
    transfers: str = "all",
    session: Session = Depends(get_session),
) -> HTMLResponse:
    if transfers not in ("all", "only", "hide"):
        transfers = "all"

    query = select(Transaction).order_by(Transaction.booking_date.desc(), Transaction.id.desc())
    if uncategorized:
        query = query.where(Transaction.category_id.is_(None))
    if transfers == "hide":
        query = query.where(Transaction.transaction_type != TransactionType.UMBUCHUNG)
    elif transfers == "only":
        query = query.where(Transaction.transaction_type == TransactionType.UMBUCHUNG)
    query = query.limit(LIST_LIMIT)
    transactions = session.exec(query).all()

    accounts_by_id, categories_by_id = _lookup_dicts(session)
    rejected_pairs = _load_rejected_pairs(session)
    rows = [
        _build_row(session, t, accounts_by_id, categories_by_id, rejected_pairs)
        for t in transactions
    ]

    all_suggestions = _pending_transfer_suggestions(session, accounts_by_id, rejected_pairs)

    return templates.TemplateResponse(
        request=request,
        name="transactions/list.html",
        context={
            "title": "Buchungen",
            "active_nav": "transactions",
            "rows": rows,
            "category_groups": _category_groups(session),
            "uncategorized_only": uncategorized,
            "transfers": transfers,
            "url_transfers_all": _filter_url(uncategorized, "all"),
            "url_transfers_only": _filter_url(uncategorized, "only"),
            "url_transfers_hide": _filter_url(uncategorized, "hide"),
            "url_uncategorized_toggle": _filter_url(not uncategorized, transfers),
            "suggestions": all_suggestions[:SUGGESTIONS_LIMIT],
            "suggestions_total": len(all_suggestions),
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
    if txn.counter_transaction_id is None:
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


@router.get("/{transaction_id}/link-form", response_class=HTMLResponse)
def link_form(
    request: Request, transaction_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    txn = session.get(Transaction, transaction_id)
    accounts_by_id, _ = _lookup_dicts(session)
    candidates = _manual_link_candidates(session, txn)
    return templates.TemplateResponse(
        request=request,
        name="transactions/_link_form.html",
        context={
            "txn": txn,
            "candidates": candidates,
            "accounts_by_id": accounts_by_id,
        },
    )


@router.post("/{transaction_id}/confirm-transfer", response_class=HTMLResponse)
def confirm_transfer(
    request: Request,
    transaction_id: int,
    counter_transaction_id: int = Form(...),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    txn, counter = _link_transactions(session, transaction_id, counter_transaction_id)
    html = _render_row_html(session, txn, oob=False)
    if counter is not None:
        html += _render_row_html(session, counter, oob=True)
    return HTMLResponse(content=html)


@router.post(
    "/suggestions/{transaction_id}/{counter_transaction_id}/confirm",
    response_class=HTMLResponse,
)
def confirm_suggestion(
    request: Request,
    transaction_id: int,
    counter_transaction_id: int,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    txn, counter = _link_transactions(session, transaction_id, counter_transaction_id)
    # Primäres Ziel (der Vorschlags-Eintrag selbst) wird leer, d.h. entfernt.
    # Betroffene Tabellenzeilen zusätzlich per Out-of-Band-Swap aktualisieren,
    # falls sie gerade in der Hauptliste sichtbar sind (sonst wirkungslos).
    html = ""
    if txn is not None:
        html += _render_row_html(session, txn, oob=True)
    if counter is not None:
        html += _render_row_html(session, counter, oob=True)
    return HTMLResponse(content=html)


@router.post(
    "/suggestions/{transaction_id}/{counter_transaction_id}/reject",
    response_class=HTMLResponse,
)
def reject_suggestion(
    request: Request,
    transaction_id: int,
    counter_transaction_id: int,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    _reject_suggestion(session, transaction_id, counter_transaction_id)
    # Vorschlags-Eintrag wird leer (entfernt). Betroffene Tabellenzeilen zusätzlich
    # per Out-of-Band-Swap aktualisieren, damit ein dort ggf. sichtbarer "Treffer"
    # ebenfalls sofort verschwindet.
    html = ""
    txn = session.get(Transaction, transaction_id)
    counter = session.get(Transaction, counter_transaction_id)
    if txn is not None:
        html += _render_row_html(session, txn, oob=True)
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
    txn.category_id = None
    session.add(txn)
    if counter is not None:
        counter.counter_transaction_id = None
        counter.transaction_type = TransactionType.EINGANG if counter.amount > 0 else TransactionType.AUSGANG
        counter.category_id = None
        session.add(counter)
    session.commit()
    session.refresh(txn)

    html = _render_row_html(session, txn, oob=False)
    if counter is not None:
        session.refresh(counter)
        html += _render_row_html(session, counter, oob=True)
    return HTMLResponse(content=html)
