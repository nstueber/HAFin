from typing import List, Optional

from sqlmodel import Field, Relationship, SQLModel

UMBUCHUNG_CATEGORY_NAME = "Umbuchung"
BARGELD_CATEGORY_NAME = "Bargeld"
PROTECTED_CATEGORY_NAMES = {UMBUCHUNG_CATEGORY_NAME, BARGELD_CATEGORY_NAME}


class Category(SQLModel, table=True):
    """Hierarchische Kategorie (Ober-/Unterkategorie), frei verwaltbar."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    parent_id: Optional[int] = Field(default=None, foreign_key="category.id")

    parent: Optional["Category"] = Relationship(
        back_populates="children",
        sa_relationship_kwargs={"remote_side": "Category.id"},
    )
    children: List["Category"] = Relationship(back_populates="parent")
