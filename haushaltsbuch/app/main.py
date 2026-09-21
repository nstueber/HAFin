from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.ingress import IngressPathMiddleware
from app.routers import (
    accounts,
    backup,
    budgets,
    categories,
    categorization_rules,
    dashboard,
    imports,
    mapping_profiles,
    settings,
    transactions,
)

BASE_DIR = Path(__file__).resolve().parent


class RevalidatingStaticFiles(StaticFiles):
    """Statische Dateien immer per ETag neu validieren (``Cache-Control: no-cache``).

    Ohne Cache-Header cachen Browser anhand von Last-Modified heuristisch. Hinter dem HA-Ingress bleibt die
    URL ueber App-Updates hinweg gleich, ein Browser kann dann nach einem Update noch das alte app.css/
    enhancements.js ausliefern (neue Seiten erscheinen ungestylt oder ohne Skript-Funktion). Zusammen mit
    dem Versions-Parameter in base.html (``?v=<version>``) ist das ausgeschlossen."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app = FastAPI(title="Haushaltsbuch")
app.add_middleware(IngressPathMiddleware)

app.mount("/static", RevalidatingStaticFiles(directory=BASE_DIR / "static"), name="static")

app.include_router(dashboard.router)
app.include_router(accounts.router)
app.include_router(transactions.router)
app.include_router(categories.router)
app.include_router(categorization_rules.router)
app.include_router(budgets.router)
app.include_router(mapping_profiles.router)
app.include_router(imports.router)
app.include_router(backup.router)
app.include_router(settings.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    mapping_profiles.cleanup_stale_uploads()
    backup.cleanup_stale_uploads()
    categories.ensure_system_categories()
    transactions.backfill_umbuchung_categories()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
