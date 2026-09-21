from pathlib import Path
from typing import Optional

from fastapi.templating import Jinja2Templates

from app.version import get_app_version

BASE_DIR = Path(__file__).resolve().parent

templates = Jinja2Templates(directory=BASE_DIR / "templates")


def format_iban(value: Optional[str]) -> str:
    """Formatiert eine kanonisch gespeicherte IBAN (ohne Leerzeichen) für die Anzeige.

    Gruppiert in 4er-Blöcke, z.B. "DE12500105170648489890" -> "DE12 5001 0517 0648 4898 90".
    """
    if not value:
        return ""
    compact = value.replace(" ", "").upper()
    return " ".join(compact[i : i + 4] for i in range(0, len(compact), 4))


def format_currency(value: Optional[float], show_sign: bool = False) -> str:
    """Formatiert einen Betrag im deutschen Zahlenformat mit Euro-Zeichen:
    "." als Tausender-, "," als Dezimaltrennzeichen, z.B. 1234.5 -> "1.234,50 €".

    NICHT fuer <input>-Werte verwenden (HTML-Zahlenfelder erwarten "."als
    Dezimaltrennzeichen) - nur fuer reine Anzeige-Texte gedacht.
    """
    if value is None:
        value = 0.0
    # Python formatiert Tausender mit "," und Dezimalstellen mit "." - fuers
    # deutsche Format ueber einen Platzhalter vertauschen.
    formatted = f"{abs(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if value < 0:
        sign = "-"
    elif show_sign:
        sign = "+"
    else:
        sign = ""
    return f"{sign}{formatted} €"


templates.env.globals["app_version"] = get_app_version()
templates.env.filters["format_iban"] = format_iban
templates.env.filters["format_currency"] = format_currency
