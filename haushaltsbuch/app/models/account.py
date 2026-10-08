from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Account(SQLModel, table=True):
    """Ein eigenes Bankkonto, dem importierte Transaktionen zugeordnet werden."""

    id: Optional[int] = Field(default=None, primary_key=True)
    iban: str = Field(index=True, unique=True)
    display_name: str
    bank_name: Optional[str] = None
    # Reserviert für spätere Nutzung: optionaler Startsaldo je Konto.
    # Aktuell nicht befuellt/verwendet.
    starting_balance: Optional[float] = None
    # Standard-Mapping-Profil dieses Kontos (optional): wird beim CSV-Import automatisch verwendet
    default_mapping_profile_id: Optional[int] = Field(default=None, foreign_key="mappingprofile.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
