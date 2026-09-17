from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.routers import accounts, mapping_profiles
from app.templating import templates

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Haushaltsbuch")

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

app.include_router(accounts.router)
app.include_router(mapping_profiles.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    mapping_profiles.cleanup_stale_uploads()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"title": "Übersicht", "active_nav": "overview"},
    )
