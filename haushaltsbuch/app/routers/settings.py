from functools import lru_cache
from pathlib import Path

import markdown
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.templating import templates

router = APIRouter(tags=["settings"])

# Kopie von THIRD-PARTY-NOTICES.md aus dem Repo-Root (der Docker-Build-Kontext ist
# "haushaltsbuch/", der Root liegt ausserhalb); der Release-Workflow prueft, dass beide gleich sind.
NOTICES_PATH = Path(__file__).resolve().parent.parent.parent / "THIRD-PARTY-NOTICES.md"


@lru_cache(maxsize=1)
def _notices_html() -> str | None:
    try:
        text = NOTICES_PATH.read_text(encoding="utf-8")
    except OSError:
        return None
    html = markdown.markdown(text, extensions=["tables"])
    # Tabellen horizontal scrollbar (schmale Displays); externe Links oeffnen ausserhalb der
    # App (in Home Assistant liegt sie in einem iframe, dort wuerde der Link sonst darin laden)
    html = html.replace("<table>", '<div class="table-scroll"><table>').replace("</table>", "</table></div>")
    return html.replace('<a href="http', '<a target="_blank" rel="noopener noreferrer" href="http')


@router.get("/settings", response_class=HTMLResponse)
def settings_hub(request: Request) -> HTMLResponse:
    """Hub-Seite "Einstellungen": Kacheln zu Konten, Kategorien, Mapping-Profilen und
    Backup & Restore (deren Routen bleiben unveraendert, nur die Navigation dorthin laeuft
    jetzt ueber diese Seite - analog zum Einstellungen-Bereich von Home Assistant)."""
    return templates.TemplateResponse(
        request=request,
        name="settings/index.html",
        context={"title": "Einstellungen", "active_nav": "settings"},
    )


@router.get("/settings/licenses", response_class=HTMLResponse)
def licenses(request: Request) -> HTMLResponse:
    """Lizenzinformationen: THIRD-PARTY-NOTICES.md als HTML (die Datei ist vertrauenswuerdig,
    Teil des Repos - kein Nutzerinhalt)."""
    return templates.TemplateResponse(
        request=request,
        name="settings/licenses.html",
        context={"title": "Lizenzinformationen", "active_nav": "licenses", "notices_html": _notices_html()},
    )
