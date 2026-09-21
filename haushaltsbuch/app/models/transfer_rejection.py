from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class RejectedTransferPair(SQLModel, table=True):
    """Ein vom Nutzer explizit abgelehnter automatischer Umbuchungs-Vorschlag.

    Wird gespeichert, damit dasselbe Buchungspaar nicht erneut als Vorschlag
    auftaucht. transaction_a_id ist immer die kleinere der beiden IDs (normalisiert),
    damit ein Paar unabhängig von der Reihenfolge eindeutig nachschlagbar ist.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    transaction_a_id: int = Field(foreign_key="transaction.id", index=True)
    transaction_b_id: int = Field(foreign_key="transaction.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
