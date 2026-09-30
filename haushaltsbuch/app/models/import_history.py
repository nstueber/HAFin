from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class ImportHistoryEntry(SQLModel, table=True):
    """Ein Eintrag der Import-Historie (nur informativ, siehe app/routers/imports.py).

    Es werden nur die letzten MAX_ENTRIES (siehe dort) vorgehalten - beim Einfuegen eines neuen
    Eintrags werden ueberzaehlige aeltere entfernt, damit die Tabelle nicht unbegrenzt waechst.
    ``account_id`` ist bewusst OHNE Fremdschluessel-Constraint (kein ``foreign_key=...``): wird das
    Konto spaeter geloescht, soll der Historien-Eintrag als Beleg des damaligen Imports bestehen
    bleiben (mit dem zum Import-Zeitpunkt gültigen Anzeigenamen, siehe ``account_name``).
    ``period_start``/``period_end`` (aeltestes/neuestes Buchungsdatum der importierten Zeilen dieses
    Imports) sind optional, damit vor Einfuehrung dieser Spalten entstandene Eintraege gueltig
    bleiben (siehe additive Spalten-Migration in app/database.py) - bei einer Datei ohne gueltige
    Zeilen (nur Fehler) bleiben sie ebenfalls ``None``.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    imported_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    account_id: Optional[int] = None
    account_name: str
    imported_count: int
    duplicate_count: int = 0
    period_start: Optional[date] = None
    period_end: Optional[date] = None
