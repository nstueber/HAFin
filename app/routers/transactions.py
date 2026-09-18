from collections import defaultdict
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlmodel import Session, select

from app.database import engine, get_session
from app.models import (
    Account,
    BARGELD_CATEGORY_NAME,
    Category,
    RejectedTransferPair,
    Transaction,
    TransactionSplit,
    TransactionType,
    UMBUCHUNG_CATEGORY_NAME,
)
from app.templating import templates

router = APIRouter(prefix="/transactions", tags=["transactions"])

LIST_LIMIT = 200
TRANSFER_WINDOW_DAYS = 2
SUGGESTIONS_LIMIT = 20
SIMILAR_PAYMENTS_LIMIT = 10
SIMILAR_TEXT_THRESHOLD = 0.6


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


def _bargeld_category_id(session: Session) -> Optional[int]:
    category = session.exec(select(Category).where(Category.name == BARGELD_CATEGORY_NAME)).first()
    return category.id if category else None


def _splits_by_transaction(session: Session, transaction_ids: list[int]) -> dict:
    if not transaction_ids:
        return {}
    splits = session.exec(
        select(TransactionSplit).where(TransactionSplit.transaction_id.in_(transaction_ids))
    ).all()
    by_txn: dict[int, list[TransactionSplit]] = defaultdict(list)
    for s in splits:
        by_txn[s.transaction_id].append(s)
    return by_txn


def backfill_umbuchung_categories() -> None:
    """Einmalige Nachbesserung fuer Umbuchungen, die verknuepft wurden, bevor
    das automatische Setzen der Kategorie "Umbuchung" eingefuehrt wurde -
    ohne das wuerde der Filter "Nur unkategorisierte" solche (bereits
    verknuepften) Umbuchungen faelschlich weiterhin als unkategorisiert
    listen. Wird bei jedem Start aufgerufen; ist bereits alles gesetzt,
    macht der Lauf nichts.
    """
    with Session(engine) as session:
        affected = session.exec(
            select(Transaction).where(
                Transaction.transaction_type == TransactionType.UMBUCHUNG,
                Transaction.counter_transaction_id.is_not(None),
                Transaction.category_id.is_(None),
            )
        ).all()
        if not affected:
            return
        umbuchung_category = _get_or_create_umbuchung_category(session)
        for txn in affected:
            txn.category_id = umbuchung_category.id
            session.add(txn)
        session.commit()


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
        select(Transaction).where(Transaction.counter_transaction_id.is_(None)).order_by(Transaction.id)
    ).all()
    seen_pairs: set = set()
    suggestions = []
    for txn in unlinked:
        for cand in _transfer_candidates(session, txn, rejected_pairs):
            pair_key = frozenset({txn.id, cand.id})
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            # a/b immer nach ID sortiert, unabhaengig davon, von welcher Seite die
            # Erkennung ausgeloest wurde - macht die Vorschlags-ID ("suggestion-X-Y")
            # deterministisch, damit spaetere OOB-Updates (z.B. Bestaetigung ueber
            # die Tabellenzeile statt ueber diese Karte) dieselbe Karte zuverlaessig
            # per ID treffen und nicht zwei Varianten derselben Kombination entstehen.
            first, second = (txn, cand) if txn.id < cand.id else (cand, txn)
            suggestions.append(
                {
                    "a": first,
                    "a_account": accounts_by_id.get(first.account_id),
                    "b": second,
                    "b_account": accounts_by_id.get(second.account_id),
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


def _filter_url(uncategorized: bool, transfers: str, date_from: str = "", date_to: str = "") -> str:
    params = []
    if uncategorized:
        params.append("uncategorized=1")
    if transfers != "all":
        params.append(f"transfers={transfers}")
    if date_from:
        params.append(f"date_from={date_from}")
    if date_to:
        params.append(f"date_to={date_to}")
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
    bargeld_category_id: Optional[int] = None,
    splits_by_txn_id: Optional[dict] = None,
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

    splits = (splits_by_txn_id or {}).get(txn.id, [])

    return {
        "txn": txn,
        "account": accounts_by_id.get(txn.account_id),
        "suggested_category": categories_by_id.get(suggested_id) if suggested_id else None,
        "counter_txn": counter_txn,
        "counter_account": counter_account,
        "transfer_candidates": transfer_candidates,
        "is_bargeld": bargeld_category_id is not None and txn.category_id == bargeld_category_id,
        "split_count": len(splits),
    }


def _render_row_html(session: Session, txn: Transaction, oob: bool) -> str:
    accounts_by_id, categories_by_id = _lookup_dicts(session)
    rejected_pairs = _load_rejected_pairs(session)
    bargeld_category_id = _bargeld_category_id(session)
    splits_by_txn_id = _splits_by_transaction(session, [txn.id])
    row = _build_row(
        session,
        txn,
        accounts_by_id,
        categories_by_id,
        rejected_pairs,
        bargeld_category_id,
        splits_by_txn_id,
    )
    template = templates.env.get_template("transactions/_row.html")
    return template.render(row=row, category_groups=_category_groups(session), oob=oob)


def _parse_date(value: str):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _apply_transaction_filters(
    query,
    uncategorized: bool,
    transfers: str,
    date_from: str = "",
    date_to: str = "",
):
    if uncategorized:
        query = query.where(Transaction.category_id.is_(None))
    if transfers == "hide":
        query = query.where(Transaction.transaction_type != TransactionType.UMBUCHUNG)
    elif transfers == "only":
        query = query.where(Transaction.transaction_type == TransactionType.UMBUCHUNG)
    from_date = _parse_date(date_from)
    to_date = _parse_date(date_to)
    if from_date is not None:
        query = query.where(Transaction.booking_date >= from_date)
    if to_date is not None:
        query = query.where(Transaction.booking_date <= to_date)
    return query


def _filtered_query(uncategorized: bool, transfers: str, date_from: str = "", date_to: str = ""):
    return _apply_transaction_filters(select(Transaction), uncategorized, transfers, date_from, date_to)


def _count_transactions(
    session: Session, uncategorized: bool, transfers: str, date_from: str = "", date_to: str = ""
) -> int:
    # select(func.count()).select_from(...) statt select(Transaction).with_only_columns(...):
    # Letzteres verliert beim Spaltenaustausch die implizite FROM-Klausel (ergibt
    # "SELECT count(*)" ganz ohne "FROM transaction" und damit ein falsches Ergebnis).
    query = _apply_transaction_filters(
        select(func.count()).select_from(Transaction), uncategorized, transfers, date_from, date_to
    )
    return session.exec(query).one()


def _category_display_name(category_id: Optional[int], categories_by_id: dict) -> str:
    """Voller Kategorie-Name inkl. Oberkategorie fuer die Suche, z.B. "Auto Ladekosten" -
    damit eine Suche nach der Oberkategorie auch Buchungen findet, deren Unterkategorie
    zugewiesen ist, und umgekehrt eine Suche nach der Unterkategorie ebenfalls greift."""
    if category_id is None:
        return ""
    cat = categories_by_id.get(category_id)
    if cat is None:
        return ""
    if cat.parent_id is not None:
        parent = categories_by_id.get(cat.parent_id)
        if parent is not None:
            return f"{parent.name} {cat.name}"
    return cat.name


def _text_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _similar_payments(session: Session, txn: Transaction, categories_by_id: dict) -> dict:
    """Findet Buchungen mit identischem Betrag+Verwendungszweck ("exakt", konto-
    uebergreifend) bzw. gleichem Betrag ODER aehnlichem Verwendungszweck ("aehnlich").
    Nutzt fuer den Text-Vergleich bewusst das Standardbibliotheks-Modul difflib statt
    einer echten Levenshtein-Bibliothek - fuer eine Vorschlagsliste (kein automatisches
    Matching) reicht diese einfache, nachvollziehbare Heuristik. Fehlt der Verwendungs-
    zweck, wird ersatzweise der Auftraggeber/Empfaenger verglichen.
    """
    txn_text = (txn.purpose or "").strip().lower() or txn.payee.strip().lower()
    candidates = session.exec(select(Transaction).where(Transaction.id != txn.id)).all()

    exact: list[Transaction] = []
    similar: list[tuple[Transaction, bool, float]] = []
    for c in candidates:
        c_text = (c.purpose or "").strip().lower() or c.payee.strip().lower()
        same_amount = c.amount == txn.amount
        same_text = bool(txn_text) and bool(c_text) and txn_text == c_text
        if same_amount and same_text:
            exact.append(c)
            continue
        ratio = _text_similarity(txn_text, c_text) if txn_text and c_text else 0.0
        if same_amount or ratio >= SIMILAR_TEXT_THRESHOLD:
            similar.append((c, same_amount, ratio))

    exact.sort(key=lambda c: c.booking_date, reverse=True)
    similar.sort(key=lambda item: (item[1], item[2], item[0].booking_date), reverse=True)

    def _as_result(c: Transaction) -> dict:
        return {"txn": c, "category": categories_by_id.get(c.category_id)}

    return {
        "exact": [_as_result(c) for c in exact[:SIMILAR_PAYMENTS_LIMIT]],
        "exact_total": len(exact),
        "similar": [_as_result(c) for c, _same_amount, _ratio in similar[:SIMILAR_PAYMENTS_LIMIT]],
        "similar_total": len(similar),
    }


@router.get("", response_class=HTMLResponse)
def list_transactions(
    request: Request,
    uncategorized: bool = False,
    transfers: str = "all",
    date_from: str = "",
    date_to: str = "",
    session: Session = Depends(get_session),
) -> HTMLResponse:
    if transfers not in ("all", "only", "hide"):
        transfers = "all"

    query = _filtered_query(uncategorized, transfers, date_from, date_to).order_by(
        Transaction.booking_date.desc(), Transaction.id.desc()
    ).limit(LIST_LIMIT)
    transactions = session.exec(query).all()
    total_count = _count_transactions(session, uncategorized, transfers, date_from, date_to)

    accounts_by_id, categories_by_id = _lookup_dicts(session)
    rejected_pairs = _load_rejected_pairs(session)
    bargeld_category_id = _bargeld_category_id(session)
    splits_by_txn_id = _splits_by_transaction(session, [t.id for t in transactions])
    rows = [
        _build_row(
            session,
            t,
            accounts_by_id,
            categories_by_id,
            rejected_pairs,
            bargeld_category_id,
            splits_by_txn_id,
        )
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
            "date_from": date_from,
            "date_to": date_to,
            "url_transfers_all": _filter_url(uncategorized, "all", date_from, date_to),
            "url_transfers_only": _filter_url(uncategorized, "only", date_from, date_to),
            "url_transfers_hide": _filter_url(uncategorized, "hide", date_from, date_to),
            "url_uncategorized_toggle": _filter_url(not uncategorized, transfers, date_from, date_to),
            "url_clear_dates": _filter_url(uncategorized, transfers),
            "search_url": f"/transactions/search-rows?uncategorized={'true' if uncategorized else 'false'}&transfers={transfers}&date_from={date_from}&date_to={date_to}",
            "suggestions": all_suggestions[:SUGGESTIONS_LIMIT],
            "suggestions_total": len(all_suggestions),
            "visible_count": len(rows),
            "total_count": total_count,
            "limit": LIST_LIMIT,
        },
    )


SEARCH_LIMIT = 500


@router.get("/search-rows", response_class=HTMLResponse)
def search_transaction_rows(
    request: Request,
    q: str = "",
    negate: bool = False,
    uncategorized: bool = False,
    transfers: str = "all",
    date_from: str = "",
    date_to: str = "",
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Server-seitige Volltextsuche (inkl. Kategorie-Name) ueber den GESAMTEN
    zum aktiven Filter passenden Datenbestand - nicht nur ueber die per
    LIST_LIMIT geladenen Zeilen. Ersetzt bei aktiver Suche den Tabelleninhalt
    komplett (inkl. aktualisierter "Zeige X von Y"-Trefferzahl); Sortierung
    bleibt weiterhin client-seitig ueber List.js auf den zurueckgegebenen Zeilen.
    """
    if transfers not in ("all", "only", "hide"):
        transfers = "all"

    query = _filtered_query(uncategorized, transfers, date_from, date_to).order_by(
        Transaction.booking_date.desc(), Transaction.id.desc()
    )
    all_matching = session.exec(query).all()

    accounts_by_id, categories_by_id = _lookup_dicts(session)

    query_lower = q.strip().lower()
    if query_lower:
        def _matches(t: Transaction) -> bool:
            haystack = " ".join(
                filter(
                    None,
                    [
                        t.payee,
                        t.purpose,
                        accounts_by_id[t.account_id].display_name if t.account_id in accounts_by_id else None,
                        _category_display_name(t.category_id, categories_by_id),
                    ],
                )
            ).lower()
            found = query_lower in haystack
            return (not found) if negate else found

        matched = [t for t in all_matching if _matches(t)]
    else:
        matched = all_matching

    transactions = matched[:SEARCH_LIMIT]

    rejected_pairs = _load_rejected_pairs(session)
    bargeld_category_id = _bargeld_category_id(session)
    splits_by_txn_id = _splits_by_transaction(session, [t.id for t in transactions])
    category_groups = _category_groups(session)
    # Bewusst KEINE Mischung aus rohen <tr>-Elementen (das eigentliche innerHTML-
    # Swap-Ziel #transaction-rows ist ein <tbody>) mit einem zusaetzlichen, anders
    # benannten Out-of-Band-Element in derselben Antwort - htmx' Fragment-Parsing
    # dafuer ist fragil und endete hier zuverlaessig in einem htmx:swapError
    # ("e.querySelectorAll is not a function"). Die "Zeige X von Y"-Trefferzahl
    # wird stattdessen rein clientseitig aus der Zeilenzahl nach dem Swap
    # abgeleitet (siehe enhancements.js, hafinInitTable's "updated"-Handler).
    # Bei 0 Treffern bleibt der <tbody> bewusst leer statt eine Platzhalter-<tr>
    # zu rendern, damit diese clientseitige Zaehlung exakt bleibt; die "Keine
    # Treffer"-Meldung wird separat (außerhalb des <tbody>) ein-/ausgeblendet.
    rows_html = "".join(
        templates.env.get_template("transactions/_row.html").render(
            row=_build_row(
                session,
                t,
                accounts_by_id,
                categories_by_id,
                rejected_pairs,
                bargeld_category_id,
                splits_by_txn_id,
            ),
            category_groups=category_groups,
            oob=False,
        )
        for t in transactions
    )
    return HTMLResponse(content=rows_html)


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


@router.post("/bulk-category", response_class=HTMLResponse)
def bulk_set_category(
    request: Request,
    transaction_ids: list[int] = Form(default=[]),
    bulk_category_id: str = Form(""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    category_id = int(bulk_category_id) if bulk_category_id else None
    txns = []
    for tid in transaction_ids:
        txn = session.get(Transaction, tid)
        # Umbuchungen (verknuepft) haben eine gesperrte, feste Kategorie -
        # bei einer Mehrfachauswahl still ueberspringen statt einen Fehler zu werfen.
        if txn is None or txn.counter_transaction_id is not None:
            continue
        txn.category_id = category_id
        session.add(txn)
        txns.append(txn)
    session.commit()

    html = ""
    for txn in txns:
        session.refresh(txn)
        html += _render_row_html(session, txn, oob=True)
    return HTMLResponse(content=html)


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


def _suggestion_card_oob_delete(transaction_id: int, counter_transaction_id: int) -> str:
    # <tr> statt <div>: dieser Platzhalter wird nie selbst angezeigt (hx-swap-oob="delete"
    # findet und entfernt das ECHTE Element mit dieser ID anhand der ID, unabhaengig vom
    # eigenen Tag des Platzhalters) - aber der Aufrufer (confirm_transfer) beginnt seine
    # Antwort mit einer echten <tr>, wodurch htmx die GESAMTE Antwort automatisch in
    # <table><tbody> einwickelt; ein <div> an dieser Stelle wuerde dort per Foster-
    # Parenting aus dem tbody herausgeloest und ging beim Extrahieren des Fragments
    # verloren (leise, ohne Fehler) - mit <tr> bleibt die Antwort durchgehend aus
    # gleichartigen Elementen zusammengesetzt und wird zuverlaessig geparst.
    a_id, b_id = sorted((transaction_id, counter_transaction_id))
    return f'<tr id="suggestion-{a_id}-{b_id}" hx-swap-oob="delete"></tr>'


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
    # Falls dasselbe Paar zufällig auch in der globalen Vorschläge-Karte
    # sichtbar ist (Bestätigung erfolgte hier direkt aus der Tabellenzeile,
    # nicht über die Karte selbst) - deren Karte ebenfalls entfernen, damit
    # sie nicht als scheinbar "zweiter" (bereits erledigter) Vorschlag stehen bleibt.
    html += _suggestion_card_oob_delete(transaction_id, counter_transaction_id)
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


def _split_form_context(session: Session, txn: Transaction, form_error: str = "") -> dict:
    splits = session.exec(
        select(TransactionSplit)
        .where(TransactionSplit.transaction_id == txn.id)
        .order_by(TransactionSplit.id)
    ).all()
    categories_by_id = {c.id: c for c in session.exec(select(Category)).all()}
    split_rows = [
        {
            "amount_magnitude": abs(s.amount),
            "category_id": s.category_id,
        }
        for s in splits
    ]
    allocated = sum(abs(s.amount) for s in splits)
    remaining_magnitude = abs(txn.amount) - allocated
    return {
        "txn": txn,
        "split_rows": split_rows,
        "remaining_magnitude": remaining_magnitude,
        "original_magnitude": abs(txn.amount),
        "category_groups": _category_groups(session),
        "form_error": form_error,
    }


@router.get("/{transaction_id}/split-form", response_class=HTMLResponse)
def split_form(
    request: Request, transaction_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    txn = session.get(Transaction, transaction_id)
    return templates.TemplateResponse(
        request=request,
        name="transactions/_split_form.html",
        context=_split_form_context(session, txn),
    )


@router.post("/{transaction_id}/splits", response_class=HTMLResponse)
def save_splits(
    request: Request,
    transaction_id: int,
    split_amount: list[str] = Form(default=[]),
    split_category_id: list[str] = Form(default=[]),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    txn = session.get(Transaction, transaction_id)
    sign = 1 if txn.amount >= 0 else -1

    new_splits: list[tuple[float, int]] = []
    total_magnitude = 0.0
    for amount_str, category_str in zip(split_amount, split_category_id):
        amount_str = amount_str.strip()
        if not amount_str or not category_str:
            continue
        try:
            magnitude = abs(float(amount_str.replace(",", ".")))
        except ValueError:
            continue
        if magnitude <= 0:
            continue
        total_magnitude += magnitude
        new_splits.append((sign * magnitude, int(category_str)))

    if total_magnitude > abs(txn.amount) + 1e-9:
        return templates.TemplateResponse(
            request=request,
            name="transactions/_split_form.html",
            context=_split_form_context(
                session,
                txn,
                form_error="Die Summe der Aufteilungen darf den Betrag der Original-Buchung nicht übersteigen.",
            ),
            status_code=400,
        )

    # Bestehende Splits vollstaendig ersetzen - einfachstes robustes Muster fuer
    # "speichere den gesamten Formularzustand auf einmal" (Zeilen hinzufuegen/
    # aendern/entfernen laeuft alles ueber denselben Save-Aufruf).
    existing = session.exec(
        select(TransactionSplit).where(TransactionSplit.transaction_id == transaction_id)
    ).all()
    for s in existing:
        session.delete(s)
    for amount, category_id in new_splits:
        session.add(
            TransactionSplit(transaction_id=transaction_id, amount=amount, category_id=category_id)
        )
    session.commit()
    session.refresh(txn)

    html = templates.env.get_template("transactions/_split_form.html").render(
        **_split_form_context(session, txn)
    )
    # Die Antwort geht in #split-dialog-content (ein <div>, kein Tabellenkontext) -
    # ein nackter <tr hx-swap-oob> waere hier vom Browser NICHT als Tabellenzeile
    # geparst worden (htmx wrapt eine Antwort nur dann automatisch in <table><tbody>,
    # wenn sie komplett mit "<tr" beginnt; hier beginnt sie mit dem Split-Formular).
    # Ohne eigenen Table-Kontext verwirft der Browser die <tr>/<td>-Starttags beim
    # Parsen (Foster-Parenting-Regel) und haengt deren KINDER (Kategorie-Select,
    # "Aufteilen bearbeiten"-Link, Mehrfachauswahl-Checkbox, ...) direkt/ungewrapped
    # in den Dialog - genau das im Screenshot gemeldete Symptom, inkl. der Checkbox,
    # die dadurch versehentlich am globalen Mehrfachauswahl-Zustand haengt. Fix: die
    # OOB-Zeile in ein eigenes, verstecktes <table><tbody> einbetten, damit sie
    # unabhaengig vom Rest der Antwort als gueltige Tabellenzeile geparst wird; htmx
    # entfernt sie beim OOB-Swap ohnehin aus dem Fragment, das leere Table-Geruest
    # bleibt unsichtbar (display:none) zurueck.
    html += f'<table style="display:none"><tbody>{_render_row_html(session, txn, oob=True)}</tbody></table>'
    return HTMLResponse(content=html)


def _detail_context(
    session: Session,
    txn: Transaction,
    edit_open: bool = False,
    edit_error: str = "",
    edit_values: Optional[dict] = None,
) -> dict:
    accounts_by_id, categories_by_id = _lookup_dicts(session)
    return {
        "txn": txn,
        "account": accounts_by_id.get(txn.account_id),
        "category": categories_by_id.get(txn.category_id),
        "accounts": sorted(accounts_by_id.values(), key=lambda a: a.display_name),
        "edit_open": edit_open,
        "edit_error": edit_error,
        "edit_values": edit_values,
        **_similar_payments(session, txn, categories_by_id),
    }


@router.get("/{transaction_id}/details", response_class=HTMLResponse)
def transaction_details(
    request: Request, transaction_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    txn = session.get(Transaction, transaction_id)
    return templates.TemplateResponse(
        request=request,
        name="transactions/_detail.html",
        context=_detail_context(session, txn),
    )


@router.post("/{transaction_id}/comment", response_class=HTMLResponse)
def update_transaction_comment(
    request: Request,
    transaction_id: int,
    comment: str = Form(""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    txn = session.get(Transaction, transaction_id)
    txn.comment = comment.strip() or None
    session.add(txn)
    session.commit()
    session.refresh(txn)
    return templates.TemplateResponse(
        request=request,
        name="transactions/_detail.html",
        context=_detail_context(session, txn),
    )


@router.post("/{transaction_id}/edit", response_class=HTMLResponse)
def update_transaction(
    request: Request,
    transaction_id: int,
    booking_date: str = Form(...),
    payee: str = Form(...),
    purpose: str = Form(""),
    amount: str = Form(...),
    account_id: int = Form(...),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    txn = session.get(Transaction, transaction_id)
    submitted = {
        "booking_date": booking_date,
        "payee": payee,
        "purpose": purpose,
        "amount": amount,
        "account_id": account_id,
    }

    def _reject(message: str) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="transactions/_detail.html",
            context=_detail_context(session, txn, edit_open=True, edit_error=message, edit_values=submitted),
            status_code=400,
        )

    # Verknuepfte Umbuchungen haben ein festes Betrags-/Konto-Verhaeltnis zur
    # Gegenbuchung (exakt entgegengesetzter Betrag, unterschiedliches Konto) - ein
    # freies Bearbeiten koennte das unbemerkt kaputt machen. Erst Verknuepfung
    # aufheben, dann bearbeiten (dieselbe Einschraenkung wie fuer die Kategorie).
    if txn.counter_transaction_id is not None:
        return _reject("Diese Buchung ist Teil einer Umbuchung - Verknüpfung erst aufheben, um sie zu bearbeiten.")

    parsed_date = _parse_date(booking_date)
    if parsed_date is None:
        return _reject("Ungültiges Datum.")
    try:
        parsed_amount = float(amount.strip().replace(",", "."))
    except ValueError:
        return _reject("Ungültiger Betrag.")
    if not payee.strip():
        return _reject("Auftraggeber/Empfänger darf nicht leer sein.")
    if session.get(Account, account_id) is None:
        return _reject("Unbekanntes Konto.")

    txn.booking_date = parsed_date
    txn.payee = payee.strip()
    txn.purpose = purpose.strip() or None
    txn.amount = parsed_amount
    txn.account_id = account_id
    txn.transaction_type = TransactionType.EINGANG if parsed_amount > 0 else TransactionType.AUSGANG
    session.add(txn)
    session.commit()
    session.refresh(txn)

    html = templates.env.get_template("transactions/_detail.html").render(**_detail_context(session, txn))
    # Siehe Kommentar in save_splits() - Haupttabellenzeile per OOB aktualisieren,
    # dafuer in ein eigenes <table><tbody> gewickelt, da die Antwort insgesamt
    # nicht mit einer <tr> beginnt (Ziel ist #transaction-detail-dialog-content).
    html += f'<table style="display:none"><tbody>{_render_row_html(session, txn, oob=True)}</tbody></table>'
    return HTMLResponse(content=html)


@router.post("/{transaction_id}/delete", response_class=HTMLResponse)
def delete_transaction(
    request: Request, transaction_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    txn = session.get(Transaction, transaction_id)
    if txn is None:
        return HTMLResponse(content="")

    # Gegenbuchung einer bestaetigten Umbuchung bleibt bestehen, verliert aber die
    # Verknuepfung (und die dadurch feste Kategorie "Umbuchung") - nicht mitloeschen.
    counter = session.get(Transaction, txn.counter_transaction_id) if txn.counter_transaction_id else None
    if counter is not None:
        counter.counter_transaction_id = None
        counter.transaction_type = TransactionType.EINGANG if counter.amount > 0 else TransactionType.AUSGANG
        counter.category_id = None
        session.add(counter)

    # Bargeld-Splits der geloeschten Buchung haben ohne sie keine Bedeutung mehr
    # (Cascade Delete) - die App hat kein Soft-Delete-Konzept, daher echtes Loeschen.
    for split in session.exec(
        select(TransactionSplit).where(TransactionSplit.transaction_id == transaction_id)
    ).all():
        session.delete(split)

    session.delete(txn)
    session.commit()

    # Antwort besteht ausschliesslich aus Out-of-Band-Elementen (geloeschte Zeile per
    # hx-swap-oob="delete", ggf. aktualisierte Gegenbuchungszeile) - das eigentliche
    # hx-target ist ein neutraler, immer vorhandener Platzhalter (siehe transactions/
    # list.html), analog zum bereits bewaehrten Muster in bulk_set_category().
    html = f'<tr id="transaction-row-{transaction_id}" hx-swap-oob="delete"></tr>'
    if counter is not None:
        session.refresh(counter)
        html += _render_row_html(session, counter, oob=True)
    return HTMLResponse(content=html)
