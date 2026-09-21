"""Budgets pro Kategorie (Einstellungen -> Budgets): monatlicher Betrag je Ober-/Unterkategorie.

Die Auswertung (Fortschrittsbalken) steht im Dashboard (``app.routers.dashboard``).
"""

import math
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.database import get_session
from app.models import UMBUCHUNG_KEY, Category, CategoryBudget
from app.templating import templates

router = APIRouter(prefix="/budgets", tags=["budgets"])

MAX_BUDGET = 1_000_000_000


def _tree(session: Session) -> list[dict]:
    """Kategorien als Baum (Oberkategorie + Unterkategorien), ohne die Systemkategorie "Umbuchung"."""
    cats = [
        c
        for c in session.exec(select(Category).order_by(Category.name)).all()
        if c.system_key != UMBUCHUNG_KEY
    ]
    by_parent: dict[int, list[Category]] = {}
    for c in cats:
        if c.parent_id is not None:
            by_parent.setdefault(c.parent_id, []).append(c)
    top_ids = {c.id for c in cats if c.parent_id is None}
    tree = [{"cat": c, "children": by_parent.get(c.id, [])} for c in cats if c.parent_id is None]
    # Unterkategorien ohne (auswaehlbare) Oberkategorie wie Oberkategorien behandeln
    tree += [{"cat": c, "children": []} for c in cats if c.parent_id is not None and c.parent_id not in top_ids]
    return tree


def _format_amount(value: float) -> str:
    return f"{value:.2f}"


def _page_context(session: Session, values: Optional[dict[int, str]] = None, **extra) -> dict:
    stored = {b.category_id: b.monthly_amount for b in session.exec(select(CategoryBudget)).all()}
    if values is None:
        values = {cid: _format_amount(amount) for cid, amount in stored.items()}
    return {
        "title": "Budgets",
        "active_nav": "budgets",
        "tree": _tree(session),
        "values": values,
        "budget_count": len(stored),
        **extra,
    }


def _parse_amount(raw: str) -> float:
    """"" -> 0.0 (kein Budget); erlaubt Komma oder Punkt als Dezimaltrennzeichen."""
    text = raw.strip().replace("€", "").replace(" ", "")
    if not text:
        return 0.0
    if "," in text and "." in text:  # 1.234,56 (deutsch)
        text = text.replace(".", "")
    text = text.replace(",", ".")
    amount = float(text)
    if not math.isfinite(amount) or amount < 0 or amount > MAX_BUDGET:
        raise ValueError("Betrag außerhalb des gültigen Bereichs")
    return round(amount, 2)


@router.get("", response_class=HTMLResponse)
def budgets_page(request: Request, saved: int = 0, session: Session = Depends(get_session)) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="budgets/list.html", context=_page_context(session, saved=bool(saved))
    )


@router.post("", response_class=HTMLResponse)
async def save_budgets(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    raw_values = {
        int(key[len("budget_"):]): str(value)
        for key, value in form.items()
        if key.startswith("budget_") and key[len("budget_"):].isdigit()
    }
    valid_ids = {c.id for c in session.exec(select(Category)).all()}
    parsed: dict[int, float] = {}
    errors: list[str] = []
    by_id = {c.id: c for c in session.exec(select(Category)).all()}
    for cid, raw in raw_values.items():
        if cid not in valid_ids:
            continue
        try:
            parsed[cid] = _parse_amount(raw)
        except ValueError:
            errors.append(by_id[cid].name)
    if errors:
        return templates.TemplateResponse(
            request=request,
            name="budgets/list.html",
            context=_page_context(
                session,
                values=raw_values,
                form_error="Ungültiger Betrag bei: " + ", ".join(errors) + ". Bitte eine Zahl ≥ 0 eingeben.",
            ),
            status_code=400,
        )
    existing = {b.category_id: b for b in session.exec(select(CategoryBudget)).all()}
    for cid, amount in parsed.items():
        budget = existing.get(cid)
        if amount <= 0:
            if budget is not None:
                session.delete(budget)  # leer/0 = kein Budget
        elif budget is not None:
            budget.monthly_amount = amount
            session.add(budget)
        else:
            session.add(CategoryBudget(category_id=cid, monthly_amount=amount))
    session.commit()
    return RedirectResponse(url="/budgets?saved=1", status_code=303)
