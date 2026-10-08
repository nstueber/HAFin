"""Import-Historie: rein informativer Nachweis der letzten CSV-Importe (siehe app/routers/imports.py)."""

from datetime import date

from sqlalchemy import text
from sqlmodel import Session, delete, select

from app.models import Account, ImportHistoryEntry, MappingProfile

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
    mapping_profile_id: int | None = None,
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
            mapping_profile_id=mapping_profile_id,
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


_BACKFILL_FLAG = "default_mapping_backfill_done"
_SINGLE_PROFILE_FLAG = "default_mapping_single_profile_done"


def _flag_done(session: Session, key: str) -> bool:
    return session.execute(text("SELECT 1 FROM app_meta WHERE key = :k"), {"k": key}).first() is not None


def _set_flag(session: Session, key: str) -> None:
    session.execute(text("INSERT INTO app_meta (key, value) VALUES (:k, '1')"), {"k": key})


def backfill_default_mapping_profiles(session: Session) -> int:
    """Einmalige Migration des Standard-Mapping-Profils je Konto (idempotent ueber Merker in ``app_meta``,
    damit ein spaeter bewusst geleertes Standard-Mapping nicht erneut befuellt wird). Zwei getrennte Schritte:

    1. *Historie:* je Konto ohne Standard das Profil, das laut Import-Historie bei diesem Konto verwendet
       wurde - nur wenn es eindeutig ist (genau ein verschiedenes, noch existierendes Profil). Nie importiert,
       mehrere Profile oder Historie ohne Profil-Angabe (Eintraege aus der Zeit vor dieser Spalte) -> offen.
    2. *Einziges Profil:* existiert im gesamten System genau EIN Mapping-Profil, bekommen alle Konten, die
       danach noch keinen Standard haben, dieses (keine Alternative -> eindeutig, kein Raten). Bei mehreren
       Profilen bleibt die Zuordnung leer und entsteht beim naechsten Import des Kontos.

    Jeder Schritt hat einen eigenen Merker, damit Schritt 2 auch bei Datenbanken laeuft, in denen Schritt 1
    bereits (ohne Ergebnis) gelaufen ist. Gibt die Zahl der gesetzten Zuordnungen zurueck."""
    assigned = 0
    profile_ids = set(session.exec(select(MappingProfile.id)).all())

    if not _flag_done(session, _BACKFILL_FLAG):
        for account in session.exec(select(Account).where(Account.default_mapping_profile_id.is_(None))).all():
            used = set(
                session.exec(
                    select(ImportHistoryEntry.mapping_profile_id).where(
                        ImportHistoryEntry.account_id == account.id,
                        ImportHistoryEntry.mapping_profile_id.is_not(None),
                    )
                ).all()
            )
            if len(used) == 1:
                pid = next(iter(used))
                if pid in profile_ids:
                    account.default_mapping_profile_id = pid
                    session.add(account)
                    assigned += 1
        session.flush()
        _set_flag(session, _BACKFILL_FLAG)

    if not _flag_done(session, _SINGLE_PROFILE_FLAG):
        if len(profile_ids) == 1:
            only = next(iter(profile_ids))
            for account in session.exec(select(Account).where(Account.default_mapping_profile_id.is_(None))).all():
                account.default_mapping_profile_id = only
                session.add(account)
                assigned += 1
        _set_flag(session, _SINGLE_PROFILE_FLAG)

    session.commit()
    return assigned
