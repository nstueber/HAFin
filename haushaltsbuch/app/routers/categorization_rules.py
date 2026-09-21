"""Verwaltung der automatischen Kategorisierungsregeln (Einstellungen -> Kategorisierungsregeln).

Die Regeln selbst wendet ``app.services.rules`` an (CSV-Import, rueckwirkende Anwendung).
"""

from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlmodel import Session, select

from app.database import get_session
from app.models import (
    RULE_FIELDS,
    RULE_MODES,
    RULE_OPERATORS,
    UMBUCHUNG_KEY,
    CategorizationRule,
    Category,
    Transaction,
    TransactionType,
)
from app.services import rules as rules_svc
from app.services.category_tree import categories_by_id, category_groups, category_path
from app.templating import templates

router = APIRouter(prefix="/categorization-rules", tags=["categorization-rules"])

MAX_VALUE_LENGTH = 200


def _form_lookups(session: Session) -> dict:
    """Auswahllisten der Regel-Formulare (Neu-Dialog und Bearbeiten-Seite)."""
    return {
        "category_groups": category_groups(session, exclude_system_keys=[UMBUCHUNG_KEY]),
        "rule_fields": RULE_FIELDS,
        "rule_operators": RULE_OPERATORS,
        "rule_modes": RULE_MODES,
    }


def _list_context(session: Session, **extra) -> dict:
    by_id = categories_by_id(session)
    rules = rules_svc.load_rules(session)
    rows = [
        {
            "rule": r,
            "field_label": RULE_FIELDS.get(r.field, r.field),
            "operator_label": RULE_OPERATORS.get(r.operator, r.operator),
            "category_path": category_path(by_id.get(r.category_id), by_id),
            "is_suggestion": r.mode == "suggest",
        }
        for r in rules
    ]
    hits, uncategorized_total = rules_svc.find_rule_hits(session) if rules else ([], 0)
    if not rules:
        uncategorized_total = session.exec(
            select(func.count())
            .select_from(Transaction)
            .where(
                Transaction.category_id.is_(None),
                Transaction.transaction_type != TransactionType.UMBUCHUNG,
            )
        ).one()
    return {
        "title": "Kategorisierungsregeln",
        "active_nav": "rules",
        "rows": rows,
        "matchable_now": len(hits),
        "uncategorized_total": uncategorized_total,
        **_form_lookups(session),
        **extra,
    }


def _validate(
    session: Session, field: str, operator: str, value: str, category_id: str, mode: str = "assign"
) -> tuple[Optional[dict], str]:
    """(bereinigte Werte, Fehlermeldung)."""
    value = value.strip()
    if field not in RULE_FIELDS:
        return None, "Bitte ein gültiges Feld wählen."
    if operator not in RULE_OPERATORS:
        return None, "Bitte einen gültigen Operator wählen."
    if mode not in RULE_MODES:
        return None, "Bitte wählen, ob die Kategorie fest zugewiesen oder nur vorgeschlagen werden soll."
    if not value:
        return None, "Bitte einen Vergleichswert eingeben."
    if len(value) > MAX_VALUE_LENGTH:
        return None, f"Der Vergleichswert ist zu lang (maximal {MAX_VALUE_LENGTH} Zeichen)."
    category = session.get(Category, int(category_id)) if category_id.isdigit() else None
    if category is None:
        return None, "Bitte eine Ziel-Kategorie wählen."
    if category.system_key == UMBUCHUNG_KEY:
        return None, "Die Systemkategorie „Umbuchung“ wird nur über die Umbuchungs-Verknüpfung gesetzt."
    return {
        "field": field,
        "operator": operator,
        "value": value,
        "category_id": category.id,
        "mode": mode,
    }, ""


def _prefill_from_transaction(session: Session, transaction_id: int) -> Optional[dict]:
    """Formularvorbelegung fuer "Regel aus dieser Buchung erstellen"."""
    txn = session.get(Transaction, transaction_id)
    if txn is None:
        return None
    purpose = (txn.purpose or "").strip()
    payee = (txn.payee or "").strip()
    use_purpose = bool(purpose)
    return {
        "form": {
            "field": "purpose" if use_purpose else "payee",
            "operator": "contains",
            "value": purpose if use_purpose else payee,
            "category_id": str(txn.category_id) if txn.category_id else "",
            "mode": "assign",
        },
        "source": {"payee": payee, "purpose": purpose},
    }


def _render_list_fragment(request: Request, session: Session) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="categorization_rules/_list.html", context=_list_context(session)
    )


@router.get("", response_class=HTMLResponse)
def list_rules(
    request: Request,
    applied: Optional[int] = None,
    suggested: int = 0,
    skipped: int = 0,
    from_transaction: Optional[int] = None,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    extra: dict = {"applied": applied, "applied_suggested": suggested, "applied_skipped": skipped}
    if from_transaction is not None:
        prefill = _prefill_from_transaction(session, from_transaction)
        if prefill:
            extra.update(open_new_dialog=True, form=prefill["form"], prefill_source=prefill["source"])
    return templates.TemplateResponse(
        request=request, name="categorization_rules/list.html", context=_list_context(session, **extra)
    )


@router.post("", response_class=HTMLResponse)
def create_rule(
    request: Request,
    field: str = Form(""),
    operator: str = Form("contains"),
    value: str = Form(""),
    category_id: str = Form(""),
    mode: str = Form("assign"),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    cleaned, error = _validate(session, field, operator, value, category_id, mode)
    if error:
        return templates.TemplateResponse(
            request=request,
            name="categorization_rules/list.html",
            context=_list_context(
                session,
                form_error=error,
                open_new_dialog=True,
                form={
                    "field": field,
                    "operator": operator,
                    "value": value,
                    "category_id": category_id,
                    "mode": mode,
                },
            ),
            status_code=400,
        )
    next_position = (session.exec(select(func.max(CategorizationRule.position))).one() or 0) + 1
    session.add(CategorizationRule(position=next_position, **cleaned))
    session.commit()
    return RedirectResponse(url="/categorization-rules", status_code=303)


@router.get("/apply", response_class=HTMLResponse)
def apply_preview(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    """Vorschau der rueckwirkenden Anwendung: Treffer auf bestehende unkategorisierte Buchungen, einzeln abwaehlbar."""
    by_id = categories_by_id(session)
    hits, uncategorized_total = rules_svc.find_rule_hits(session)
    rows = [
        {
            "txn": h.txn,
            "rule": h.rule,
            "rule_text": f"{rules_svc.describe_rule(h.rule)} „{h.rule.value}“",
            "category_path": category_path(by_id.get(h.rule.category_id), by_id),
            "is_suggestion": h.rule.mode == "suggest",
        }
        for h in hits
    ]
    return templates.TemplateResponse(
        request=request,
        name="categorization_rules/apply.html",
        context={
            "title": "Regeln anwenden",
            "active_nav": "rules",
            "rows": rows,
            "uncategorized_total": uncategorized_total,
        },
    )


@router.post("/apply", response_class=HTMLResponse)
def apply_rules(
    hit: list[str] = Form(default=[]), session: Session = Depends(get_session)
) -> RedirectResponse:
    """Wendet die in der Vorschau angehakten Treffer an (``hit`` = "<Buchungs-ID>:<Regel-ID>")."""
    pairs: list[tuple[int, int]] = []
    for value in hit:
        txn_part, _, rule_part = value.partition(":")
        if txn_part.isdigit() and rule_part.isdigit():
            pairs.append((int(txn_part), int(rule_part)))
    result = rules_svc.apply_selected_hits(session, pairs)
    session.commit()
    return RedirectResponse(
        url=f"/categorization-rules?applied={result['assigned']}"
        f"&suggested={result['suggested']}&skipped={result['skipped']}",
        status_code=303,
    )


@router.get("/{rule_id}/edit", response_class=HTMLResponse)
def edit_rule_form(request: Request, rule_id: int, session: Session = Depends(get_session)):
    rule = session.get(CategorizationRule, rule_id)
    if rule is None:
        return RedirectResponse(url="/categorization-rules", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="categorization_rules/edit.html",
        context={
            "title": "Regel bearbeiten",
            "active_nav": "rules",
            "rule": rule,
            "form": {
                "field": rule.field,
                "operator": rule.operator,
                "value": rule.value,
                "category_id": str(rule.category_id),
                "mode": rule.mode,
            },
            **_form_lookups(session),
        },
    )


@router.post("/{rule_id}/edit", response_class=HTMLResponse)
def update_rule(
    request: Request,
    rule_id: int,
    field: str = Form(""),
    operator: str = Form("contains"),
    value: str = Form(""),
    category_id: str = Form(""),
    mode: str = Form("assign"),
    session: Session = Depends(get_session),
):
    rule = session.get(CategorizationRule, rule_id)
    if rule is None:
        return RedirectResponse(url="/categorization-rules", status_code=303)
    cleaned, error = _validate(session, field, operator, value, category_id, mode)
    if error:
        return templates.TemplateResponse(
            request=request,
            name="categorization_rules/edit.html",
            context={
                "title": "Regel bearbeiten",
                "active_nav": "rules",
                "rule": rule,
                "form": {
                    "field": field,
                    "operator": operator,
                    "value": value,
                    "category_id": category_id,
                    "mode": mode,
                },
                "form_error": error,
                **_form_lookups(session),
            },
            status_code=400,
        )
    rule.field = cleaned["field"]
    rule.operator = cleaned["operator"]
    rule.value = cleaned["value"]
    rule.category_id = cleaned["category_id"]
    rule.mode = cleaned["mode"]
    session.add(rule)
    session.commit()
    return RedirectResponse(url="/categorization-rules", status_code=303)


@router.post("/{rule_id}/delete", response_class=HTMLResponse)
def delete_rule(request: Request, rule_id: int, session: Session = Depends(get_session)) -> HTMLResponse:
    rule = session.get(CategorizationRule, rule_id)
    if rule is not None:
        session.delete(rule)
        session.commit()
    return _render_list_fragment(request, session)


@router.post("/{rule_id}/move", response_class=HTMLResponse)
def move_rule(
    request: Request,
    rule_id: int,
    direction: str = "up",
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Verschiebt eine Regel in der Prioritaetsliste um eine Stelle (up = hoehere Prioritaet).
    Die Positionen werden dabei lueckenlos neu durchnummeriert."""
    ordered = rules_svc.load_rules(session)
    index = next((i for i, r in enumerate(ordered) if r.id == rule_id), None)
    if index is not None:
        target = index - 1 if direction == "up" else index + 1
        if 0 <= target < len(ordered):
            ordered[index], ordered[target] = ordered[target], ordered[index]
        for position, rule in enumerate(ordered, start=1):
            if rule.position != position:
                rule.position = position
                session.add(rule)
        session.commit()
    return _render_list_fragment(request, session)
