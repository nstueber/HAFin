import math
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from app.database import get_session
from app.models import (
    CATEGORY_TYPE_EXPENSE,
    CATEGORY_TYPE_INCOME,
    Account,
    Category,
    CategoryBudget,
    Transaction,
    TransactionSplit,
    TransactionType,
)
from app.services.category_tree import category_path
from app.services.category_types import effective_type
from app.templating import templates

router = APIRouter(tags=["dashboard"])

GRANULARITIES = ("day", "week", "month", "year")
TRANSFER_MODES = ("all", "only", "hide")
# Umbuchungsfilter, wenn die URL keinen ``transfers``-Parameter enthaelt (erstes Laden, Menue-Link "Uebersicht").
# Der Filterzustand lebt ausschliesslich in der URL (kein localStorage/Cookie) - ein ausdruecklich gewaehlter Wert,
# auch "all", steht deshalb immer explizit in der URL und wird nie durch den Standard ueberschrieben.
DEFAULT_TRANSFERS = "hide"
# Vorzeitraumsvergleich (Balken-Diagramme): wie beim Umbuchungsfilter lebt der Zustand nur in der
# URL (Checkbox ohne "checked" sendet beim Absenden gar keinen Parameter -> Standard "aus").
DEFAULT_COMPARE = False
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
    granularity: str,
    ref: date,
    transfers: str,
    account_id: Optional[int],
    compare: bool = False,
) -> str:
    params = [f"granularity={granularity}", f"ref={ref.isoformat()}"]
    if transfers != DEFAULT_TRANSFERS:
        params.append(f"transfers={transfers}")
    if account_id is not None:
        params.append(f"account_id={account_id}")
    if compare:
        params.append("compare=1")
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


def _category_entries(txns: list[Transaction], categories_by_id: dict, splits_by_txn_id: dict) -> list[dict]:
    """Zerlegt jede Buchung in einen oder mehrere (Oberkategorie, Betrag)-Eintraege.

    Buchungen ohne Splits ergeben genau einen Eintrag (ihre eigene Kategorie,
    voller Betrag). Buchungen MIT Splits (z.B. teilweise aufgeteiltes Bargeld)
    ergeben mehrere Eintraege: den nicht aufgeteilten Rest bei der Original-
    Kategorie plus je einen Eintrag pro Split bei dessen eigener Kategorie -
    in Summe weiterhin exakt der Original-Betrag, keine Doppelzaehlung.
    """
    entries = []
    for t in txns:
        splits = splits_by_txn_id.get(t.id, [])
        if splits:
            allocated = sum(s.amount for s in splits)
            remainder = t.amount - allocated
            entries.append(
                {
                    "category_id": t.category_id,
                    "top_category_id": _top_level_category_id(t.category_id, categories_by_id),
                    "amount": remainder,
                    "txn": t,
                    "is_split_portion": False,
                }
            )
            for s in splits:
                entries.append(
                    {
                        "category_id": s.category_id,
                        "top_category_id": _top_level_category_id(s.category_id, categories_by_id),
                        "amount": s.amount,
                        "txn": t,
                        "is_split_portion": True,
                    }
                )
        else:
            entries.append(
                {
                    "category_id": t.category_id,
                    "top_category_id": _top_level_category_id(t.category_id, categories_by_id),
                    "amount": t.amount,
                    "txn": t,
                    "is_split_portion": False,
                }
            )
    return entries


def _drilldown_url(
    granularity: str,
    ref: date,
    transfers: str,
    account_id: Optional[int],
    kind: str,
    category_key: Optional[str] = None,
    exact: bool = False,
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
    if exact:
        params.append("exact=true")
    return "/dashboard/transactions?" + "&".join(params)


def _raw_top_sums(entries: list[dict]) -> dict:
    """Netto-Summe je Oberkategorie (Schluessel wie ``top_category_id``: ``None`` = unkategorisiert),
    OHNE Vorzeichen-Anpassung an einen Diagrammtyp - Rohwert fuer den Vorzeitraumsvergleich."""
    sums: dict = defaultdict(float)
    for e in entries:
        sums[e["top_category_id"]] += e["amount"]
    return sums


def _period_diff(cur_signed: float, prev_raw: float, sign: int) -> dict:
    """Veraenderung einer Kategorie ggue. dem Vorzeitraum, im selben Vorzeichen-System wie der
    Balkenwert (``cur_signed``), damit ein positiver ``diff`` in beiden Diagrammen "mehr von diesem
    Kategorie-Typ" bedeutet. ``is_new``: Vorzeitraum war (rechnerisch) 0 - Prozent ergibt keinen Sinn
    ("neu" statt Division durch 0)."""
    prev_signed = sign * prev_raw
    diff = cur_signed - prev_signed
    is_new = abs(prev_signed) < 0.005
    return {
        "diff": diff,
        "percent": None if is_new else diff / prev_signed * 100,
        "is_new": is_new,
    }


def _category_chart_data(
    entries: list[dict],
    categories_by_id: dict,
    granularity: str,
    ref_date: date,
    transfers: str,
    account_id_int: Optional[int],
    prev_top_sums: Optional[dict] = None,
) -> dict:
    """Baut die fuer Chart.js direkt verwendbaren Datenstrukturen der Kategorie-Aufschluesselung -
    getrennt nach Kategorie-Typ: ``{"expense": ..., "income": ...}`` (Ausgaben- bzw. Einnahmen-Diagramm).

    Jedes Diagramm enthaelt sowohl den einfachen (ein Balken je Oberkategorie) als auch den gestapelten
    Modus (ein Segment je tatsaechlich zugewiesener Unterkategorie), damit beide Modi client-seitig ohne
    erneuten Server-Request umgeschaltet werden koennen.

    Die Zuordnung zum Diagramm richtet sich nach dem Typ der Oberkategorie (nicht nach dem Namen):
    Typ "ausgabe" -> Ausgaben (Balken = -Summe), "einnahme" -> Einnahmen (Balken = +Summe). Ohne Typ
    (Unkategorisiert, Systemkategorie Umbuchung) entscheidet das Vorzeichen der Summe wie bisher. Die
    Summe ist netto: Rueckerstattungen mindern eine Ausgabe. Netto-Summen mit umgekehrtem Vorzeichen
    (Ausgaben-Kategorie insgesamt im Plus) sowie gegenlaeufige Segmente erscheinen nicht im Diagramm
    (Balken koennen nicht negativ sein) - die Buchungen bleiben im Detail-Drilldown und in der Liste sichtbar.

    ``prev_top_sums``: Rohsummen (wie ``_raw_top_sums``) desselben Zeitraum-Ausschnitts im direkt
    vorherigen Zeitraum (nur wenn der Vorzeitraumsvergleich aktiv ist) - ``None`` laesst ``diffs``
    bei beiden Diagrammen ``None`` (kein zusaetzlicher Query, wenn der Vergleich ausgeschaltet ist).
    """
    top_sums = _raw_top_sums(entries)
    sub_sums: dict = defaultdict(float)  # (top_id, actual_category_id) -> amount
    for e in entries:
        sub_sums[(e["top_category_id"], e["category_id"])] += e["amount"]

    def chart_for(kind: str) -> dict:
        # Vorzeichen, mit dem eine Summe in diesem Diagramm positiv wird
        sign = -1 if kind == CATEGORY_TYPE_EXPENSE else 1

        def belongs(top_id: Optional[int], total: float) -> bool:
            category_type = effective_type(categories_by_id.get(top_id), categories_by_id)
            if category_type is None:  # neutral: Vorzeichen der Summe entscheidet
                return sign * total > 0
            return category_type == kind

        top_items = []
        for top_id, total in top_sums.items():
            value = sign * total
            if value <= 0 or not belongs(top_id, total):
                continue
            label = "Unkategorisiert" if top_id is None else categories_by_id[top_id].name
            key = "uncategorized" if top_id is None else str(top_id)
            diff = (
                _period_diff(value, prev_top_sums.get(top_id, 0.0), sign)
                if prev_top_sums is not None
                else None
            )
            top_items.append(
                {
                    "top_id": top_id,
                    "label": label,
                    "amount": value,
                    "uncategorized": top_id is None,
                    "key": key,
                    "diff": diff,
                }
            )
        top_items.sort(key=lambda i: i["amount"], reverse=True)

        # Segmente je Oberkategorie einsammeln (fuer den gestapelten Modus).
        segments_by_top: dict = defaultdict(list)
        for (top_id, actual_id), amount in sub_sums.items():
            if sign * amount <= 0:
                continue
            if actual_id == top_id:
                label = "Unkategorisiert" if top_id is None else "Allgemein"
            else:
                label = categories_by_id[actual_id].name if actual_id in categories_by_id else "?"
            segments_by_top[top_id].append({"category_id": actual_id, "label": label, "amount": sign * amount})
        for segs in segments_by_top.values():
            segs.sort(key=lambda seg: seg["amount"], reverse=True)

        # Jede Oberkategorie kann eine andere Anzahl/Art von Unterkategorien haben -
        # fuer Chart.js' gestapelte Balken brauchen wir pro tatsaechlicher Kategorie
        # EIN Dataset ueber ALLE Balken hinweg (0 bei jeder anderen Oberkategorie).
        stacked_datasets = []
        for index, top_item in enumerate(top_items):
            for seg in segments_by_top.get(top_item["top_id"], []):
                data = [0] * len(top_items)
                data[index] = seg["amount"]
                stacked_datasets.append(
                    {
                        "label": seg["label"],
                        "data": data,
                        "url": _drilldown_url(
                            granularity,
                            ref_date,
                            transfers,
                            account_id_int,
                            "category",
                            "uncategorized" if seg["category_id"] is None else str(seg["category_id"]),
                            exact=True,
                        ),
                    }
                )

        return {
            "labels": [i["label"] for i in top_items],
            "simple_amounts": [i["amount"] for i in top_items],
            "simple_uncategorized": [i["uncategorized"] for i in top_items],
            "simple_urls": [
                _drilldown_url(granularity, ref_date, transfers, account_id_int, "category", i["key"])
                for i in top_items
            ],
            "diffs": [i["diff"] for i in top_items] if prev_top_sums is not None else None,
            "stacked_datasets": stacked_datasets,
        }

    return {"expense": chart_for(CATEGORY_TYPE_EXPENSE), "income": chart_for(CATEGORY_TYPE_INCOME)}


# Schwellwerte der Budget-Farbcodierung (Anteil des Budgets in Prozent)
BUDGET_WARN_PERCENT = 80  # ab hier gelb
BUDGET_LIMIT_PERCENT = 100  # darueber rot (genau 100 % ist noch gelb)


def _budget_status(percent: float) -> str:
    if percent > BUDGET_LIMIT_PERCENT:
        return "over"
    if percent >= BUDGET_WARN_PERCENT:
        return "warn"
    return "ok"


def _budget_items(
    session: Session,
    start: date,
    end: date,
    ref_date: date,
    granularity: str,
    categories_by_id: dict,
) -> list[dict]:
    """Ist-Ausgaben des Zeitraums gegen die Budgets je Kategorie: bei "month" das Monatsbudget, bei "year"
    das auf das Jahr hochgerechnete Budget (Monatsbetrag x 12). Andere Zeitraeume haben keine sinnvolle
    Umrechnung (der Aufrufer blendet den Bereich dort aus).

    Immer ueber alle Konten und OHNE Umbuchungen (Budgets betreffen echte Ausgaben; der Konto-Filter
    des Dashboards gilt nur fuer das Kategorie-Diagramm). Zaehlung wie beim Kategorie-Diagramm: fuer eine
    Oberkategorie alles inkl. ihrer Unterkategorien (Roll-up), fuer eine Unterkategorie nur ihre eigenen
    Buchungen - Bargeld-Splits werden beruecksichtigt. Eine Unterkategorie zaehlt also zugleich in ihr
    eigenes Budget und (falls gesetzt) in das der Oberkategorie.
    """
    months = 12 if granularity == "year" else 1
    budgets = {b.category_id: b.monthly_amount for b in session.exec(select(CategoryBudget)).all()}
    if not budgets:
        return []
    txns = _period_transactions(session, start, end, "hide")
    entries = _category_entries(
        txns, categories_by_id, _splits_by_transaction(session, [t.id for t in txns])
    )
    by_actual: dict = defaultdict(float)
    by_top: dict = defaultdict(float)
    for e in entries:
        by_actual[e["category_id"]] += e["amount"]
        by_top[e["top_category_id"]] += e["amount"]

    items = []
    for category_id, budget in budgets.items():
        category = categories_by_id.get(category_id)
        if category is None or budget <= 0:
            continue
        is_top_level = category.parent_id is None
        net = (by_top if is_top_level else by_actual).get(category_id, 0.0)
        # In ganzen Cent rechnen (Float-Summen wie 79.99999999 duerfen keine Schwelle verfehlen);
        # Erstattungen mindern die Ausgaben, ein Guthaben ergibt kein "negatives" Ausgeben.
        spent_cents = max(0, round(-net * 100))
        budget_cents = round(budget * months * 100)
        spent = spent_cents / 100
        percent = spent_cents * 100 / budget_cents
        status = _budget_status(percent)
        items.append(
            {
                "category_id": category_id,
                "label": category_path(category, categories_by_id),
                "budget": budget_cents / 100,
                "monthly": budget,
                "spent": spent,
                "percent": percent,
                # Anzeige passt zur Farbe: ueberzogen wird aufgerundet (nie "100 %" in Rot), sonst abgerundet
                # (nie "80 %" in Gruen)
                "percent_label": math.ceil(percent) if status == "over" else math.floor(percent),
                "bar_width": min(percent, 100.0),
                "remaining": budget_cents / 100 - spent,
                "status": status,
                "url": _drilldown_url(
                    granularity, ref_date, "hide", None, "category", str(category_id), exact=not is_top_level
                ),
            }
        )
    items.sort(key=lambda i: (-i["percent"], i["label"]))
    return items


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    granularity: str = "month",
    ref: Optional[str] = None,
    transfers: str = DEFAULT_TRANSFERS,
    account_id: str = "",
    compare: str = "",
    session: Session = Depends(get_session),
) -> HTMLResponse:
    if granularity not in GRANULARITIES:
        granularity = "month"
    if transfers not in TRANSFER_MODES:
        transfers = DEFAULT_TRANSFERS
    # Wie granularity/transfers: ein Rohstring statt bool, damit ein ungueltiger/handgeschriebener
    # Wert nicht mit 422 abgewiesen wird, sondern (wie ueberall sonst) still auf den Standard faellt.
    compare_flag = compare == "1"
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
    splits_by_txn_id = _splits_by_transaction(session, [t.id for t in breakdown_txns])
    breakdown_entries = _category_entries(breakdown_txns, categories_by_id, splits_by_txn_id)

    prev_ref = _shift_ref(granularity, start, -1)
    next_ref = _shift_ref(granularity, start, 1)

    # Vorzeitraumsvergleich: derselbe direkt vorherige Zeitraum wie beim "<"-Navigationspfeil
    # (identische _shift_ref()/_period_bounds()-Berechnung - Monats-/Jahresgrenzen also garantiert
    # konsistent mit der Navigation, keine eigene Datumsarithmetik). Nur bei aktivem Vergleich
    # geladen, um den zusaetzlichen Query im Normalfall zu vermeiden.
    prev_top_sums = None
    if compare_flag:
        prev_start, prev_end = _period_bounds(granularity, prev_ref)
        prev_txns = _period_transactions(session, prev_start, prev_end, transfers)
        prev_breakdown_txns = [
            t for t in prev_txns if account_id_int is None or t.account_id == account_id_int
        ]
        prev_splits_by_txn_id = _splits_by_transaction(session, [t.id for t in prev_breakdown_txns])
        prev_entries = _category_entries(prev_breakdown_txns, categories_by_id, prev_splits_by_txn_id)
        prev_top_sums = _raw_top_sums(prev_entries)

    chart_data = _category_chart_data(
        breakdown_entries,
        categories_by_id,
        granularity,
        ref_date,
        transfers,
        account_id_int,
        prev_top_sums,
    )

    # Budgets sind monatliche Werte: in der Monatsansicht direkt, in der Jahresansicht x 12; bei Tag/Woche
    # gibt es keine sinnvolle Umrechnung (das Template blendet den Bereich dann aus)
    budget_items = (
        _budget_items(session, start, end, ref_date, granularity, categories_by_id)
        if granularity in ("month", "year")
        else []
    )

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "title": "Übersicht",
            "active_nav": "overview",
            "granularity": granularity,
            "period_label": _period_label(granularity, start, end),
            "url_granularity": {
                g: _dashboard_url(g, ref_date, transfers, account_id_int, compare_flag) for g in GRANULARITIES
            },
            "url_prev": _dashboard_url(granularity, prev_ref, transfers, account_id_int, compare_flag),
            "url_next": _dashboard_url(granularity, next_ref, transfers, account_id_int, compare_flag),
            "transfers": transfers,
            "compare": compare_flag,
            "budget_items": budget_items,
            "total_tile": total_tile,
            "account_tiles": account_tiles,
            "accounts": accounts,
            "selected_account_id": account_id_int,
            "ref": ref_date.isoformat(),
            "chart_data": chart_data,
        },
    )


@router.get("/dashboard/transactions", response_class=HTMLResponse)
def dashboard_transactions(
    request: Request,
    granularity: str = "month",
    ref: Optional[str] = None,
    transfers: str = DEFAULT_TRANSFERS,
    account_id: str = "",
    kind: str = "net",
    category: str = "",
    exact: bool = False,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Liefert die Buchungen hinter einer angeklickten Zahl im Dashboard (Kennzahlen-
    Kachel oder Kategorie-Balken) als Fragment fuer das Drilldown-Modal - beruecksichtigt
    dieselben Zeitraum-/Konto-/Umbuchungsfilter wie die Dashboard-Ansicht selbst.
    """
    if granularity not in GRANULARITIES:
        granularity = "month"
    if transfers not in TRANSFER_MODES:
        transfers = DEFAULT_TRANSFERS
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
    accounts_by_id = {a.id: a for a in session.exec(select(Account)).all()}

    if kind in ("income", "expense", "net"):
        # Einnahmen/Ausgaben/Netto sind unabhaengig von Kategorie-Splits (die
        # Original-Buchung behaelt ihren vollen, unveraenderten Betrag) - hier
        # zaehlt nur das Vorzeichen des tatsaechlichen Buchungsbetrags.
        if kind == "income":
            txns = [t for t in txns if t.amount > 0]
        elif kind == "expense":
            txns = [t for t in txns if t.amount < 0]
        txns.sort(key=lambda t: (t.booking_date, t.id), reverse=True)
        entries = [
            {
                "booking_date": t.booking_date,
                "account_name": accounts_by_id[t.account_id].display_name
                if t.account_id in accounts_by_id
                else "–",
                "payee": t.payee,
                "purpose": t.purpose,
                "amount": t.amount,
                "is_split_portion": False,
            }
            for t in txns
        ]
    else:
        # "category": beruecksichtigt Splits - eine teilweise aufgeteilte
        # Bargeld-Buchung kann hier sowohl mit ihrem Rest (Original-Kategorie)
        # als auch mit einem Split-Anteil (Ziel-Kategorie) auftauchen, jeweils
        # nur mit dem tatsaechlich dieser Kategorie zugeordneten Teilbetrag.
        splits_by_txn_id = _splits_by_transaction(session, [t.id for t in txns])
        all_entries = _category_entries(txns, categories_by_id, splits_by_txn_id)

        def _matches_category(entry: dict) -> bool:
            # "exact": Klick auf ein einzelnes Unterkategorie-Segment im gestapelten
            # Chart-Modus - nur dessen eigene (Split-)Eintraege, ohne Geschwister-
            # Unterkategorien. Ohne "exact" (Klick auf den ganzen Balken im
            # einfachen Modus oder auf eine Kachel): die ganze Oberkategorie
            # inkl. aller Unterkategorien (Roll-up), wie bisher.
            actual_id = entry["category_id"] if exact else entry["top_category_id"]
            if category == "uncategorized":
                return actual_id is None
            return category.isdigit() and actual_id == int(category)

        matching = [e for e in all_entries if _matches_category(e)]
        matching.sort(key=lambda e: (e["txn"].booking_date, e["txn"].id), reverse=True)
        entries = [
            {
                "booking_date": e["txn"].booking_date,
                "account_name": accounts_by_id[e["txn"].account_id].display_name
                if e["txn"].account_id in accounts_by_id
                else "–",
                "payee": e["txn"].payee,
                "purpose": e["txn"].purpose,
                "amount": e["amount"],
                "is_split_portion": e["is_split_portion"],
            }
            for e in matching
        ]

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
            "entries": entries,
        },
    )
