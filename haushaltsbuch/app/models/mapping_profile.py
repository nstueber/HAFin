from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class MappingProfile(SQLModel, table=True):
    """Wiederverwendbares CSV-Mapping-Profil (z.B. eines pro Bank).

    Legt fest, wie eine Bank-CSV geparst wird (Trennzeichen, Dezimaltrennzeichen,
    Zeichenkodierung, Datumsformat) und welche CSV-Spalten welchen fachlichen
    Feldern entsprechen.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)

    # CSV-Parsing-Konfiguration
    delimiter: str = Field(default=",")
    decimal_separator: str = Field(default=".")
    encoding: str = Field(default="utf-8")
    date_format: str = Field(default="%Y-%m-%d")
    # 0-basierter Index der Kopfzeile in der Rohdatei - alles davor (z.B.
    # Metadaten-Präambel mancher Bank-Exports) wird beim Parsen übersprungen.
    header_row_index: int = Field(default=0)

    # Spaltenzuordnung: Namen der CSV-Header-Spalten
    date_column: str
    payee_column: str
    purpose_column: str
    amount_column: str

    created_at: datetime = Field(default_factory=datetime.utcnow)
