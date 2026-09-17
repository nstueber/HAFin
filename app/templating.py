from pathlib import Path
from typing import Optional

from fastapi.templating import Jinja2Templates

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


templates.env.filters["format_iban"] = format_iban
