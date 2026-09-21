from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

# Erlaubte Werte (als Strings gespeichert - einfacher zu exportieren/migrieren als ein Enum)
RULE_FIELDS = {"purpose": "Verwendungszweck", "payee": "Auftraggeber/Empfänger"}
RULE_OPERATORS = {"contains": "enthält", "starts_with": "beginnt mit", "equals": "ist exakt"}
# "assign": Kategorie wird fest gesetzt; "suggest": nur als Vorschlag an der Buchung hinterlegt
# (Transaction.suggested_category_id), die Buchung bleibt unkategorisiert
RULE_MODES = {"assign": "Kategorie fest zuweisen", "suggest": "Nur als Vorschlag anzeigen"}


class CategorizationRule(SQLModel, table=True):
    """Automatische Kategorisierungsregel, angewendet beim CSV-Import (und auf Wunsch rueckwirkend).

    ``position`` legt die Prioritaet fest: kleinere Zahl = weiter oben = hoehere Prioritaet; bei
    mehreren passenden Regeln gewinnt die mit der kleinsten Position. Verglichen wird ohne
    Beachtung von Gross-/Kleinschreibung (siehe app.services.rules).
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    position: int = Field(default=0, index=True)
    field: str = Field(default="purpose")
    operator: str = Field(default="contains")
    value: str
    category_id: int = Field(foreign_key="category.id", index=True)
    mode: str = Field(default="assign")
    created_at: datetime = Field(default_factory=datetime.utcnow)
