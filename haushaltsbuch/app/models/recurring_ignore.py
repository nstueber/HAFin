from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class RecurringIgnore(SQLModel, table=True):
    """Eine vom Nutzer ignorierte "wiederkehrende Zahlung" (siehe app/services/recurring.py).

    Reine Anzeige-Einstellung: die zugrunde liegenden Buchungen bleiben unveraendert. Eine Gruppe wird
    ueber Konto + normalisierten Auftraggeber + Vorzeichen (Einnahme/Ausgabe) wiedererkannt, nicht
    ueber Buchungs-IDs - so bleibt das Ignorieren auch bestehen, wenn neue Buchungen hinzukommen.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="account.id", index=True)
    payee_key: str
    sign: int  # -1 = Ausgabe, +1 = Einnahme
    created_at: datetime = Field(default_factory=datetime.utcnow)
