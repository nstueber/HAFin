from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.database import get_session
from app.models import Category, RecurringIgnore
from app.services import recurring as svc
from app.services.category_tree import category_groups, category_path
from app.templating import invalidate_recurring_badge, templates

router = APIRouter(prefix="/recurring", tags=["recurring"])


@router.get("", response_class=HTMLResponse)
def recurring_overview(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    series = svc.detect(session)
    return templates.TemplateResponse(
        request=request,
        name="recurring/list.html",
        context={
            "title": "Wiederkehrende Zahlungen",
            "active_nav": "recurring",
            "active": [s for s in series if not s.ignored and not s.ended],
            "ended": [s for s in series if not s.ignored and s.ended],
            "ignored": [s for s in series if s.ignored],
            "min_occurrences": svc.MIN_OCCURRENCES,
        },
    )


@router.get("/detail", response_class=HTMLResponse)
def recurring_detail(
    request: Request,
    account_id: int,
    sign: int,
    first_id: int,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Detailansicht einer erkannten Reihe (Fragment fuer den Dialog): alle Buchungen mit Datum, Betrag
    und Kategorie + Summe der letzten 12 Monate. Dieselbe Ansicht oeffnet sich beim Klick auf die
    Bezeichnung und auf das Ausrufezeichen bei uneinheitlicher Kategorisierung."""
    series = svc.find_member_series(svc.detect(session), account_id, 1 if sign > 0 else -1, first_id)
    if series is None:
        return templates.TemplateResponse(
            request=request, name="recurring/_detail.html", context={"series": None}
        )
    categories = {c.id: c for c in session.exec(select(Category)).all()}
    rows = [
        {
            "txn": m,
            "category_name": category_path(categories[m.category_id], categories)
            if m.category_id in categories
            else "Unkategorisiert",
        }
        for m in series.members
    ]
    return templates.TemplateResponse(
        request=request,
        name="recurring/_detail.html",
        context={
            "series": series,
            "rows": rows[::-1],  # neueste zuerst (List.js sortiert danach clientseitig)
            "summary": svc.twelve_month_summary(series),
            "category_groups": category_groups(session),
        },
    )


@router.post("/ignore")
def ignore_series(
    account_id: int = Form(...),
    payee_key: str = Form(...),
    sign: int = Form(...),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    """Blendet eine erkannte Gruppe dauerhaft aus (nur Anzeige - Buchungen bleiben unveraendert)."""
    sign = 1 if sign > 0 else -1
    exists = session.exec(
        select(RecurringIgnore).where(
            RecurringIgnore.account_id == account_id,
            RecurringIgnore.payee_key == payee_key,
            RecurringIgnore.sign == sign,
        )
    ).first()
    if exists is None:
        session.add(RecurringIgnore(account_id=account_id, payee_key=payee_key, sign=sign))
        session.commit()
    invalidate_recurring_badge()
    return RedirectResponse(url="/recurring", status_code=303)


@router.post("/unignore")
def unignore_series(
    account_id: int = Form(...),
    payee_key: str = Form(...),
    sign: int = Form(...),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    """Macht das Ignorieren rueckgaengig: entfernt alle Ignorier-Eintraege, die diese Gruppe treffen."""
    sign = 1 if sign > 0 else -1
    keys = {payee_key}
    for s in svc.detect(session):
        if s.account_id == account_id and s.sign == sign and s.payee_key == payee_key:
            keys |= s.member_keys
    for ig in session.exec(
        select(RecurringIgnore).where(RecurringIgnore.account_id == account_id, RecurringIgnore.sign == sign)
    ).all():
        if ig.payee_key in keys:
            session.delete(ig)
    session.commit()
    invalidate_recurring_badge()
    return RedirectResponse(url="/recurring", status_code=303)
