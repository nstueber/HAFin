from typing import Optional

from sqlmodel import Field, SQLModel


class CategoryBudget(SQLModel, table=True):
    """Monatliches Budget einer Kategorie (Ober- ODER Unterkategorie, jeweils unabhaengig).

    Kein Datensatz = kein Budget gesetzt; ein Betrag von 0 wird gar nicht erst gespeichert.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    category_id: int = Field(foreign_key="category.id", unique=True, index=True)
    monthly_amount: float
