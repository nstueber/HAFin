from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.templating import templates

router = APIRouter(tags=["settings"])


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
