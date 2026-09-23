from typing import List, Optional

from sqlmodel import Field, Relationship, SQLModel

# Feste Kennzeichen der Systemkategorien - die App referenziert diese Kategorien
# ausschliesslich ueber Category.system_key, NIE ueber den Anzeigenamen (der Name
# ist nur der Default beim erstmaligen Anlegen und bei Systemkategorien ohnehin
# nicht aenderbar).
UMBUCHUNG_KEY = "umbuchung"
BARGELD_KEY = "bargeld"
SYSTEM_CATEGORY_DEFAULT_NAMES = {
    UMBUCHUNG_KEY: "Umbuchung",
    BARGELD_KEY: "Bargeld",
}


# Kategorie-Typ: nur an Oberkategorien gepflegt, Unterkategorien erben ihn (siehe
# app.services.category_types). Die Systemkategorie "Umbuchung" hat keinen Typ (NULL).
CATEGORY_TYPE_INCOME = "einnahme"
CATEGORY_TYPE_EXPENSE = "ausgabe"
CATEGORY_TYPES = (CATEGORY_TYPE_INCOME, CATEGORY_TYPE_EXPENSE)


class Category(SQLModel, table=True):
    """Hierarchische Kategorie (Ober-/Unterkategorie), frei verwaltbar."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    parent_id: Optional[int] = Field(default=None, foreign_key="category.id")
    # Gesetzt nur bei den Systemkategorien (siehe UMBUCHUNG_KEY/BARGELD_KEY) - solche
    # Kategorien sind weder loesch- noch umbenennbar.
    system_key: Optional[str] = Field(default=None, index=True)
    # "einnahme" / "ausgabe" - nur bei Oberkategorien gesetzt (Unterkategorien erben, Feld bleibt NULL).
    type: Optional[str] = Field(default=None)

    parent: Optional["Category"] = Relationship(
        back_populates="children",
        sa_relationship_kwargs={"remote_side": "Category.id"},
    )
    children: List["Category"] = Relationship(back_populates="parent")
