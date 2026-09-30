"""Import-Historie: rein informativer Nachweis der letzten CSV-Importe (siehe app/routers/imports.py)."""

from datetime import date

from sqlmodel import Session, delete, select

from app.models import ImportHistoryEntry

MAX_ENTRIES = 20


def record_import(
    session: Session,
    *,
    account_id: int,
    account_name: str,
    imported_count: int,
    duplicate_count: int,
    period_start: date | None = None,
    period_end: date | None = None,
) -> None:
    """Fuegt einen Historien-Eintrag hinzu und kuerzt danach auf MAX_ENTRIES (aelteste zuerst
    entfernt) - insgesamt ueber alle Konten hinweg, nicht je Konto. Committet nicht selbst
    (Aufrufer haelt die Transaktion des eigentlichen Imports)."""
    session.add(
        ImportHistoryEntry(
            account_id=account_id,
            account_name=account_name,
            imported_count=imported_count,
            duplicate_count=duplicate_count,
            period_start=period_start,
            period_end=period_end,
        )
    )
    session.flush()
    ids_to_keep = session.exec(
        select(ImportHistoryEntry.id)
        .order_by(ImportHistoryEntry.imported_at.desc(), ImportHistoryEntry.id.desc())
        .limit(MAX_ENTRIES)
    ).all()
    if ids_to_keep:
        session.exec(delete(ImportHistoryEntry).where(ImportHistoryEntry.id.not_in(ids_to_keep)))


def recent_imports(session: Session, limit: int = MAX_ENTRIES) -> list[ImportHistoryEntry]:
    return list(
        session.exec(
            select(ImportHistoryEntry)
            .order_by(ImportHistoryEntry.imported_at.desc(), ImportHistoryEntry.id.desc())
            .limit(limit)
        ).all()
    )
