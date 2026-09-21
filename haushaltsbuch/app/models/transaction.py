from datetime import date, datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class TransactionType(str, Enum):
    EINGANG = "eingang"
    AUSGANG = "ausgang"
    UMBUCHUNG = "umbuchung"


class Transaction(SQLModel, table=True):
    """Eine importierte Kontobewegung.

    Betrag: negativ = Abgang vom Konto, positiv = Gutschrift auf das Konto.
    transaction_type wird beim Import aus dem Vorzeichen abgeleitet
    (eingang/ausgang) und kann manuell oder nach bestätigtem Treffer auf
    "umbuchung" gesetzt werden. counter_transaction_id verweist auf die
    verknüpfte Gegen-Transaktion einer bestätigten Umbuchung und bleibt bei
    manuell markierten, aber (noch) unverknüpften Umbuchungen leer.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="account.id", index=True)

    booking_date: date = Field(index=True)
    payee: str
    purpose: Optional[str] = None
    amount: float

    transaction_type: TransactionType = Field(default=TransactionType.AUSGANG)
    counter_transaction_id: Optional[int] = Field(default=None, foreign_key="transaction.id")

    category_id: Optional[int] = Field(default=None, foreign_key="category.id", index=True)
    # Vorschlag einer Kategorisierungsregel im Modus "nur vorschlagen" - bewusst getrennt von category_id:
    # die Buchung bleibt unkategorisiert, bis der Vorschlag uebernommen wird (dann wird er geleert).
    suggested_category_id: Optional[int] = Field(default=None, foreign_key="category.id")

    comment: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
