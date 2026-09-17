from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from app.database import get_session
from app.models import Account, Category, Transaction, TransactionType
from app.templating import templates

router = APIRouter(tags=["dashboard"])

GRANULARITIES = ("day", "week", "month", "year")
MONTH_NAMES_DE = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]


def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def _period_bounds(granularity: str, ref: date) -> tuple[date, date]:
    """Berechnet Start-/Enddatum (beide inklusive) des Zeitraums, der `ref` enthält."""
    if granularity == "day":
        return ref, ref
    if granularity == "week":
        start = ref - timedelta(days=ref.weekday())
        return start, start + timedelta(days=6)
    if granularity == "year":
        return date(ref.year, 1, 1), date(ref.year, 12, 31)
    # "month" (auch Fallback fuer unbekannte Werte)
    start = ref.replace(day=1)
    return start, _add_months(start, 1) - timedelta(days=1)


def _shift_ref(granularity: str, start: date, direction: int) -> date:
    """Liefert einen Tag innerhalb des vorherigen/naechsten Zeitraums (direction: -1/+1)."""
    if granularity == "day":
        return start + timedelta(days=direction)
    if granularity == "week":
        return start + timedelta(days=7 * direction)
    if granularity == "year":
        return date(start.year + direction, 1, 1)
    return _add_months(start, direction)


def _period_label(granularity: str, start: date, end: date) -> str:
    if granularity == "day":
        return f"{start.day}. {MONTH_NAMES_DE[start.month - 1]} {start.year}"
    if granularity == "week":
        week_no = start.isocalendar()[1]
        return f"KW {week_no} · {start.strftime('%d.%m.')}–{end.strftime('%d.%m.%Y')}"
    if granularity == "year":
        return str(start.year)
    return f"{MONTH_NAMES_DE[start.month - 1]} {start.year}"


def _dashboard_url(
    granularity: str, ref: date, transfers: str, account_id: Optional[int]
) -> str:
    params = [f"granularity={granularity}", f"ref={ref.isoformat()}"]
    if transfers != "all":
        params.append(f"transfers={transfers}")
    if account_id is not None:
        params.append(f"account_id={account_id}")
    return "/?" + "&".join(params)


def _period_transactions(
    session: Session, start: date, end: date, transfers: str
) -> list[Transaction]:
    query = select(Transaction).where(
        Transaction.booking_date >= start,
        Transaction.booking_date <= end,
    )
    if transfers == "hide":
        query = query.where(Transaction.transaction_type != TransactionType.UMBUCHUNG)
    elif transfers == "only":
        query = query.where(Transaction.transaction_type == TransactionType.UMBUCHUNG)
    return session.exec(query).all()


def _income_expense_net(txns: list[Transaction]) -> dict:
    income = sum(t.amount for t in txns if t.amount > 0)
    expense = -sum(t.amount for t in txns if t.amount < 0)
    return {"income": income, "expense": expense, "net": income - expense}


def _top_level_category_id(
    category_id: Optional[int], categories_by_id: dict
) -> Optional[int]:
    if category_id is None:
        return None
    cat = categories_by_id.get(category_id)
    if cat is None:
        return None
    return cat.parent_id if cat.parent_id is not None else cat.id


def _category_breakdown(
    txns: list[Transaction], categories_by_id: dict
) -> list[dict]:
    sums: dict = defaultdict(float)
    for t in txns:
        sums[_top_level_category_id(t.category_id, categories_by_id)] += t.amount

    items = []
    for cat_id, amount in sums.items():
        if amount == 0:
            continue
        label = "Unkategorisiert" if cat_id is None else categories_by_id[cat_id].name
        key = "uncategorized" if cat_id is None else str(cat_id)
        items.append(
            {"label": label, "amount": abs(amount), "uncategorized": cat_id is None, "key": key}
        )
    items.sort(key=lambda item: item["amount"], reverse=True)
    return items


def _drilldown_url(
    granularity: str,
    ref: date,
    transfers: str,
    account_id: Optional[int],
    kind: str,
    category_key: Optional[str] = None,
) -> str:
    params = [
        f"granularity={granularity}",
        f"ref={ref.isoformat()}",
        f"transfers={transfers}",
        f"kind={kind}",
    ]
    if account_id is not None:
        params.append(f"account_id={account_id}")
    if category_key is not None:
        params.append(f"category={category_key}")
    return "/dashboard/transactions?" + "&".join(params)


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    granularity: str = "month",
    ref: Optional[str] = None,
    transfers: str = "all",
    account_id: str = "",
    session: Session = Depends(get_session),
) -> HTMLResponse:
    if granularity not in GRANULARITIES:
        granularity = "month"
    if transfers not in ("all", "only", "hide"):
        transfers = "all"
    # Das Konto-Filter-<select> submitted bei "Alle Konten" einen leeren String
    # (nicht abwesend) - "" laesst sich nicht direkt in int parsen.
    account_id_int = int(account_id) if account_id else None
    try:
        ref_date = date.fromisoformat(ref) if ref else date.today()
    except ValueError:
        ref_date = date.today()

    start, end = _period_bounds(granularity, ref_date)

    accounts = session.exec(select(Account).order_by(Account.display_name)).all()
    if account_id_int is not None and account_id_int not in {a.id for a in accounts}:
        account_id_int = None

    txns = _period_transactions(session, start, end, transfers)

    by_account: dict[int, list[Transaction]] = defaultdict(list)
    for t in txns:
        by_account[t.account_id].append(t)

    def _tile_urls(acc_id: Optional[int]) -> dict:
        return {
            "income": _drilldown_url(granularity, ref_date, transfers, acc_id, "income"),
            "expense": _drilldown_url(granularity, ref_date, transfers, acc_id, "expense"),
            "net": _drilldown_url(granularity, ref_date, transfers, acc_id, "net"),
        }

    total_tile = {**_income_expense_net(txns), "urls": _tile_urls(None)}
    account_tiles = [
        {
            "account": acc,
            **_income_expense_net(by_account.get(acc.id, [])),
            "urls": _tile_urls(acc.id),
        }
        for acc in accounts
    ]

    categories_by_id = {c.id: c for c in session.exec(select(Category)).all()}
    breakdown_txns = [
        t for t in txns if account_id_int is None or t.account_id == account_id_int
    ]
    chart_items = _category_breakdown(breakdown_txns, categories_by_id)
    for item in chart_items:
        item["url"] = _drilldown_url(
            granularity, ref_date, transfers, account_id_int, "category", item["key"]
        )

    prev_ref = _shift_ref(granularity, start, -1)
    next_ref = _shift_ref(granularity, start, 1)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "title": "Übersicht",
            "active_nav": "overview",
            "granularity": granularity,
            "period_label": _period_label(granularity, start, end),
            "url_granularity": {
                g: _dashboard_url(g, ref_date, transfers, account_id_int) for g in GRANULARITIES
            },
            "url_prev": _dashboard_url(granularity, prev_ref, transfers, account_id_int),
            "url_next": _dashboard_url(granularity, next_ref, transfers, account_id_int),
            "transfers": transfers,
            "url_transfers_all": _dashboard_url(granularity, ref_date, "all", account_id_int),
            "url_transfers_only": _dashboard_url(granularity, ref_date, "only", account_id_int),
            "url_transfers_hide": _dashboard_url(granularity, ref_date, "hide", account_id_int),
            "total_tile": total_tile,
            "account_tiles": account_tiles,
            "accounts": accounts,
            "selected_account_id": account_id_int,
            "ref": ref_date.isoformat(),
            "chart_items": chart_items,
        },
    )


@router.get("/dashboard/transactions", response_class=HTMLResponse)
def dashboard_transactions(
    request: Request,
    granularity: str = "month",
    ref: Optional[str] = None,
    transfers: str = "all",
    account_id: str = "",
    kind: str = "net",
    category: str = "",
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Liefert die Buchungen hinter einer angeklickten Zahl im Dashboard (Kennzahlen-
    Kachel oder Kategorie-Balken) als Fragment fuer das Drilldown-Modal - beruecksichtigt
    dieselben Zeitraum-/Konto-/Umbuchungsfilter wie die Dashboard-Ansicht selbst.
    """
    if granularity not in GRANULARITIES:
        granularity = "month"
    if transfers not in ("all", "only", "hide"):
        transfers = "all"
    if kind not in ("income", "expense", "net", "category"):
        kind = "net"
    account_id_int = int(account_id) if account_id else None
    try:
        ref_date = date.fromisoformat(ref) if ref else date.today()
    except ValueError:
        ref_date = date.today()

    start, end = _period_bounds(granularity, ref_date)
    txns = _period_transactions(session, start, end, transfers)
    if account_id_int is not None:
        txns = [t for t in txns if t.account_id == account_id_int]

    categories_by_id = {c.id: c for c in session.exec(select(Category)).all()}

    if kind == "income":
        txns = [t for t in txns if t.amount > 0]
    elif kind == "expense":
        txns = [t for t in txns if t.amount < 0]
    elif kind == "category":
        def _matches_category(t: Transaction) -> bool:
            top_id = _top_level_category_id(t.category_id, categories_by_id)
            if category == "uncategorized":
                return top_id is None
            return category.isdigit() and top_id == int(category)

        txns = [t for t in txns if _matches_category(t)]

    txns.sort(key=lambda t: (t.booking_date, t.id), reverse=True)

    accounts_by_id = {a.id: a for a in session.exec(select(Account)).all()}

    title_map = {
        "income": "Einnahmen",
        "expense": "Ausgaben",
        "net": "Alle Buchungen",
        "category": (
            "Unkategorisiert"
            if category == "uncategorized"
            else categories_by_id[int(category)].name
            if category.isdigit() and int(category) in categories_by_id
            else "Kategorie"
        ),
    }

    return templates.TemplateResponse(
        request=request,
        name="_transaction_drilldown.html",
        context={
            "heading": title_map[kind],
            "period_label": _period_label(granularity, start, end),
            "transactions": txns,
            "accounts_by_id": accounts_by_id,
        },
    )
