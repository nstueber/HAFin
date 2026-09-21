from typing import Optional

from sqlmodel import Session, select

from app.models import SYSTEM_CATEGORY_DEFAULT_NAMES, Category


def get_system_category(session: Session, key: str) -> Optional[Category]:
    return session.exec(select(Category).where(Category.system_key == key)).first()


def get_or_create_system_category(session: Session, key: str) -> Category:
    """Liefert die Systemkategorie zum festen Schluessel `key` (z.B. "umbuchung").

    Aufloesung ausschliesslich ueber Category.system_key. Existiert noch keine
    Kategorie mit diesem Schluessel (Erststart bzw. Datenbank aus der Zeit vor
    dem system_key), wird einmalig eine bestehende Kategorie mit dem Default-Namen
    uebernommen (Backfill, damit bereits zugeordnete Buchungen erhalten bleiben)
    oder eine neue angelegt - danach spielt der Anzeigename keine Rolle mehr.
    """
    category = get_system_category(session, key)
    if category is not None:
        return category
    default_name = SYSTEM_CATEGORY_DEFAULT_NAMES[key]
    category = session.exec(
        select(Category)
        .where(Category.name == default_name, Category.system_key.is_(None))
        .order_by(Category.id)
    ).first()
    if category is None:
        category = Category(name=default_name)
    category.system_key = key
    session.add(category)
    session.commit()
    session.refresh(category)
    return category
