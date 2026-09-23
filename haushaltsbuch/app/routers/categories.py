import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlmodel import Session, select

from app.database import engine, get_session
from app.models import (
    CATEGORY_TYPE_EXPENSE,
    CATEGORY_TYPES,
    SYSTEM_CATEGORY_DEFAULT_NAMES,
    UMBUCHUNG_KEY,
    CategorizationRule,
    Category,
    CategoryBudget,
    Transaction,
)
from app.services.category_types import (
    TYPE_LABELS,
    backfill_category_types,
    effective_type,
)
from app.system_categories import get_or_create_system_category
from app.templating import templates

router = APIRouter(prefix="/categories", tags=["categories"])


def ensure_system_categories() -> None:
    """Stellt die festen, weder loesch- noch umbenennbaren Systemkategorien
    ("Umbuchung", "Bargeld", referenziert ueber Category.system_key) sicher -
    wird bei jedem App-Start aufgerufen, damit beide von Anfang an in jeder
    Kategorie-Auswahl auftauchen (nicht erst nach dem ersten Trigger-Ereignis
    wie einer Umbuchungs-Verknuepfung) und Datenbanken aus der Zeit vor dem
    system_key einmalig migriert werden (siehe get_or_create_system_category).
    """
    with Session(engine) as session:
        for key in SYSTEM_CATEGORY_DEFAULT_NAMES:
            get_or_create_system_category(session, key)


def backfill_types() -> None:
    """Bestimmt den Typ (Einnahme/Ausgabe) bestehender Oberkategorien einmalig (Migration, idempotent)."""
    with Session(engine) as session:
        backfill_category_types(session)


def _valid_type(value: str) -> str:
    """Formularwert -> gueltiger Kategorie-Typ (Standard: Ausgabe)."""
    return value if value in CATEGORY_TYPES else CATEGORY_TYPE_EXPENSE


def _top_level_categories(session: Session) -> list[Category]:
    return session.exec(
        select(Category).where(Category.parent_id.is_(None)).order_by(Category.name)
    ).all()


def _list_context(session: Session, **extra) -> dict:
    top_level = _top_level_categories(session)
    children_by_parent: dict[int, list[Category]] = {}
    for cat in top_level:
        children_by_parent[cat.id] = session.exec(
            select(Category).where(Category.parent_id == cat.id).order_by(Category.name)
        ).all()
    return {
        "title": "Kategorien",
        "active_nav": "categories",
        "top_level": top_level,
        "children_by_parent": children_by_parent,
        "type_labels": TYPE_LABELS,
        **extra,
    }


@router.get("", response_class=HTMLResponse)
def list_categories(
    request: Request,
    imported: int = 0,
    skipped: int = 0,
    import_error: str = "",
    session: Session = Depends(get_session),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="categories/list.html",
        context=_list_context(
            session,
            imported=imported,
            skipped=skipped,
            import_error=import_error,
        ),
    )


@router.get("/_list", response_class=HTMLResponse)
def list_categories_fragment(
    request: Request, session: Session = Depends(get_session)
) -> HTMLResponse:
    """Nur die Kategorien-Liste (ohne restliche Seite) - fuer htmx-Swaps nach
    Aktionen wie Loeschen, bei denen sich die Baumstruktur veraendern kann
    (z.B. Unterkategorien werden zu Oberkategorien befoerdert)."""
    return templates.TemplateResponse(
        request=request,
        name="categories/_list.html",
        context=_list_context(session),
    )


@router.post("", response_class=HTMLResponse)
def create_category(
    request: Request,
    name: list[str] = Form(...),
    parent_id: list[str] = Form(...),
    type: list[str] = Form(default=[]),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Legt eine oder mehrere Kategorien in einem Vorgang an (Mehrfachanlage-
    Modal: beliebig viele Name+Oberkategorie+Typ-Zeilen). Leere Namenszeilen
    (z.B. eine per JS hinzugefuegte, aber nicht ausgefuellte Zeile) werden
    dabei still uebersprungen statt einen Fehler zu werfen. Der Typ gilt nur fuer
    Oberkategorien - Unterkategorien erben ihn (das Feld der Zeile wird ignoriert)."""
    created = False
    types = list(type) + [""] * (len(name) - len(type))
    for row_name, row_parent_id, row_type in zip(name, parent_id, types):
        row_name = row_name.strip()
        if not row_name:
            continue
        parent = int(row_parent_id) if row_parent_id else None
        session.add(
            Category(
                name=row_name,
                parent_id=parent,
                type=None if parent else _valid_type(row_type),
            )
        )
        created = True
    if created:
        session.commit()
    return RedirectResponse(url="/categories", status_code=303)


def _edit_context(session: Session, category: Category, **extra) -> dict:
    by_id = {c.id: c for c in session.exec(select(Category)).all()}
    top_level = [c for c in _top_level_categories(session) if c.id != category.id]
    return {
        "title": "Kategorie bearbeiten",
        "active_nav": "categories",
        "category": category,
        "top_level": top_level,
        "current_type": effective_type(category, by_id),
        "is_neutral": category.system_key == UMBUCHUNG_KEY,
        "type_labels": TYPE_LABELS,
        # Typ jeder Oberkategorie fuer die Anzeige des geerbten Typs beim Wechsel der Oberkategorie
        "parent_types": {c.id: effective_type(c, by_id) for c in top_level},
        **extra,
    }


@router.get("/{category_id}/edit", response_class=HTMLResponse)
def edit_category_form(
    request: Request, category_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    category = session.get(Category, category_id)
    return templates.TemplateResponse(
        request=request,
        name="categories/edit.html",
        context=_edit_context(session, category),
    )


@router.post("/{category_id}/edit", response_class=HTMLResponse)
def update_category(
    request: Request,
    category_id: int,
    name: str = Form(""),
    parent_id: str = Form(""),
    type: str = Form(""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    category = session.get(Category, category_id)
    new_parent_id = int(parent_id) if parent_id else None
    new_name = name.strip()

    def _reject(message: str) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="categories/edit.html",
            context=_edit_context(session, category, form_error=message),
            status_code=400,
        )

    if category.system_key:
        # Systemkategorien behalten ihren Namen zwingend - das Namensfeld ist im
        # Formular deaktiviert (wird also gar nicht mitgeschickt), aber ein
        # direkter Request mit abweichendem Namen wird hier trotzdem abgewiesen.
        if new_name and new_name != category.name:
            return _reject("Systemkategorie, nicht änderbar: Der Name kann nicht umbenannt werden.")
        new_name = category.name
    elif not new_name:
        return _reject("Der Name darf nicht leer sein.")

    if new_parent_id == category_id:
        return _reject("Eine Kategorie kann nicht ihre eigene Oberkategorie sein.")

    # Typ: nur Oberkategorien tragen ihn (Unterkategorien erben); Umbuchung bleibt neutral.
    if category.system_key == UMBUCHUNG_KEY or new_parent_id is not None:
        new_type = None
    elif type in CATEGORY_TYPES:
        new_type = type
    else:
        new_type = category.type or _valid_type("")  # z.B. Unterkategorie wird zur Oberkategorie ohne Auswahl

    category.name = new_name
    category.parent_id = new_parent_id
    category.type = new_type
    session.add(category)
    session.commit()
    return RedirectResponse(url="/categories", status_code=303)


@router.get("/{category_id}/delete-confirm", response_class=HTMLResponse)
def delete_category_confirm(
    request: Request, category_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    category = session.get(Category, category_id)
    children = session.exec(
        select(Category).where(Category.parent_id == category_id).order_by(Category.name)
    ).all()
    transaction_count = len(
        session.exec(select(Transaction).where(Transaction.category_id == category_id)).all()
    )
    rule_count = len(
        session.exec(
            select(CategorizationRule).where(CategorizationRule.category_id == category_id)
        ).all()
    )
    has_budget = (
        session.exec(select(CategoryBudget).where(CategoryBudget.category_id == category_id)).first()
        is not None
    )
    return templates.TemplateResponse(
        request=request,
        name="categories/_delete_confirm.html",
        context={
            "category": category,
            "children": children,
            "transaction_count": transaction_count,
            "rule_count": rule_count,
            "has_budget": has_budget,
        },
    )


@router.post("/{category_id}/delete", response_class=HTMLResponse)
def delete_category(
    request: Request, category_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    category = session.get(Category, category_id)
    if category is None:
        return HTMLResponse(content="")
    if category.system_key:
        # Sollte ueber die UI nicht erreichbar sein (kein Loeschen-Button) -
        # trotzdem serverseitig verweigern, falls doch direkt angefragt.
        return Response(status_code=403)

    # Unterkategorien werden zu eigenstaendigen Oberkategorien, statt die
    # Loeschung zu blockieren oder sie mit zu loeschen.
    children = session.exec(select(Category).where(Category.parent_id == category_id)).all()
    for child in children:
        child.parent_id = None
        child.type = category.type or CATEGORY_TYPE_EXPENSE  # behaelt den bisher geerbten Typ
        session.add(child)

    # Zugeordnete Buchungen werden unkategorisiert, nicht mitgeloescht.
    affected_txns = session.exec(
        select(Transaction).where(Transaction.category_id == category_id)
    ).all()
    for txn in affected_txns:
        txn.category_id = None
        session.add(txn)

    # Regeln mit dieser Ziel-Kategorie und ein Budget fuer sie ergeben ohne die Kategorie keinen Sinn.
    for rule in session.exec(
        select(CategorizationRule).where(CategorizationRule.category_id == category_id)
    ).all():
        session.delete(rule)
    for budget in session.exec(
        select(CategoryBudget).where(CategoryBudget.category_id == category_id)
    ).all():
        session.delete(budget)

    # Regel-Vorschlaege auf diese Kategorie entfallen
    for txn in session.exec(
        select(Transaction).where(Transaction.suggested_category_id == category_id)
    ).all():
        txn.suggested_category_id = None
        session.add(txn)

    session.delete(category)
    session.commit()

    return templates.TemplateResponse(
        request=request,
        name="categories/_list.html",
        context=_list_context(session),
    )


@router.get("/export")
def export_categories(session: Session = Depends(get_session)) -> Response:
    top_level = _top_level_categories(session)
    data = []
    for cat in top_level:
        children = session.exec(
            select(Category).where(Category.parent_id == cat.id).order_by(Category.name)
        ).all()
        data.append({"name": cat.name, "type": cat.type, "children": [c.name for c in children]})
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="kategorien.json"'},
    )


@router.post("/import")
async def import_categories(
    request: Request,
    json_file: UploadFile,
    session: Session = Depends(get_session),
) -> RedirectResponse:
    try:
        raw = await json_file.read()
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("Erwartet wurde eine Liste von Oberkategorien.")
    except Exception:
        message = quote("Die Datei ist kein gültiges Kategorien-JSON.")
        return RedirectResponse(url=f"/categories?import_error={message}", status_code=303)

    existing_top_level = _top_level_categories(session)
    top_level_by_name = {c.name.lower(): c for c in existing_top_level}

    imported = 0
    skipped = 0

    for entry in data:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        top_name = str(entry["name"]).strip()
        if not top_name:
            continue

        parent = top_level_by_name.get(top_name.lower())
        if parent is None:
            parent = Category(name=top_name, parent_id=None, type=_valid_type(str(entry.get("type", ""))))
            session.add(parent)
            session.commit()
            session.refresh(parent)
            top_level_by_name[top_name.lower()] = parent
            imported += 1
        else:
            skipped += 1

        existing_children = {
            c.name.lower(): c
            for c in session.exec(
                select(Category).where(Category.parent_id == parent.id)
            ).all()
        }
        for child_name in entry.get("children", []) or []:
            child_name = str(child_name).strip()
            if not child_name:
                continue
            if child_name.lower() in existing_children:
                skipped += 1
                continue
            child = Category(name=child_name, parent_id=parent.id)
            session.add(child)
            session.commit()
            existing_children[child_name.lower()] = child
            imported += 1

    return RedirectResponse(
        url=f"/categories?imported={imported}&skipped={skipped}", status_code=303
    )
