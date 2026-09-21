"""Kategorienbaum-Hilfen, die von mehreren Seiten (Buchungsliste, Regeln, Budgets) gebraucht werden."""

from typing import Iterable, Optional

from sqlmodel import Session, select

from app.models import Category


def category_groups(session: Session, exclude_system_keys: Iterable[str] = ()) -> list[dict]:
    """Kategorien gruppiert fuer die Dropdown-Darstellung (Optgroups je Oberkategorie).

    ``exclude_system_keys``: Systemkategorien (z.B. "umbuchung"), die nicht auswaehlbar sein sollen.
    """
    excluded = set(exclude_system_keys)
    cats = [
        c
        for c in session.exec(select(Category).order_by(Category.name)).all()
        if c.system_key not in excluded
    ]
    children_by_parent: dict[int, list[Category]] = {}
    for c in cats:
        if c.parent_id is not None:
            children_by_parent.setdefault(c.parent_id, []).append(c)
    top_ids = {c.id for c in cats if c.parent_id is None}
    return [
        {
            "id": c.id,
            "name": c.name,
            "children": [{"id": ch.id, "name": ch.name} for ch in children_by_parent.get(c.id, [])],
        }
        for c in cats
        if c.parent_id is None
    ] + [
        # Unterkategorien, deren Oberkategorie ausgeschlossen wurde, erscheinen als eigene Eintraege
        {"id": c.id, "name": c.name, "children": []}
        for c in cats
        if c.parent_id is not None and c.parent_id not in top_ids
    ]


def categories_by_id(session: Session) -> dict[int, Category]:
    return {c.id: c for c in session.exec(select(Category)).all()}


def category_path(category: Optional[Category], by_id: dict[int, Category]) -> str:
    """"Ober › Unter" bzw. nur der Name einer Oberkategorie."""
    if category is None:
        return "–"
    parent = by_id.get(category.parent_id) if category.parent_id else None
    return f"{parent.name} › {category.name}" if parent else category.name
