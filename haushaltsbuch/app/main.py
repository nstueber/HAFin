from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.ingress import IngressPathMiddleware
from app.routers import accounts, categories, dashboard, imports, mapping_profiles, transactions

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Haushaltsbuch")
app.add_middleware(IngressPathMiddleware)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

app.include_router(dashboard.router)
app.include_router(accounts.router)
app.include_router(transactions.router)
app.include_router(categories.router)
app.include_router(mapping_profiles.router)
app.include_router(imports.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    mapping_profiles.cleanup_stale_uploads()
    categories.ensure_system_categories()
    transactions.backfill_umbuchung_categories()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
