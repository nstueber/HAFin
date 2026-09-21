from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class TransactionSplit(SQLModel, table=True):
    """Manuelle Teil-Zuordnung einer Buchung (z.B. Bargeld-Abhebung) zu einer
    anderen Kategorie als der Original-Buchung.

    Die Original-Buchung (transaction_id) bleibt unveraendert bestehen (Betrag,
    Kategorie); ein Split verschiebt lediglich einen Teilbetrag "amount" (mit
    demselben Vorzeichen wie die Original-Buchung) gedanklich in category_id.
    Die Summe aller Split-Betraege einer Buchung darf den Betrag der
    Original-Buchung (nach Betrag) nicht uebersteigen - der nicht aufgeteilte
    Rest bleibt bei der Original-Kategorie.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    transaction_id: int = Field(foreign_key="transaction.id", index=True)
    amount: float
    category_id: int = Field(foreign_key="category.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
