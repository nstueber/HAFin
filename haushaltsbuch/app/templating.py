from pathlib import Path
from typing import Optional

from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app.ingress import get_ingress_prefix
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


def ingress_base_path(request: Request) -> str:
    """Fuer ``base.html``: validierter Ingress-Praefix des aktuellen Requests, eingebettet als
    ``window.HB_BASE_PATH`` - Grundlage des ``hbUrl()``-Helpers in ``enhancements.js`` (siehe
    ``app/ingress.py`` fuer den Hintergrund). ``request`` steht dank ``TemplateResponse(request=...)``
    in jedem Template automatisch zur Verfuegung."""
    return get_ingress_prefix(request)


templates.env.globals["app_version"] = get_app_version()
templates.env.globals["ingress_base_path"] = ingress_base_path
templates.env.filters["format_iban"] = format_iban
templates.env.filters["format_currency"] = format_currency
