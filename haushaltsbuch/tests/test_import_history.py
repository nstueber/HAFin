"""Unit-Tests: Import-Historie + einmalige Migration des Standard-Mapping-Profils je Konto."""

from sqlalchemy import text
from sqlmodel import select

from app.models import Account, ImportHistoryEntry, MappingProfile
from app.services.import_history import MAX_ENTRIES, backfill_default_mapping_profiles, record_import


def _prepare(session):
    session.execute(text("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"))
    session.commit()


def _account(session, iban):
    acc = Account(iban=iban, display_name=iban)
    session.add(acc)
    session.commit()
    session.refresh(acc)
    return acc


def _profile(session, name):
    p = MappingProfile(
        name=name, date_column="d", payee_column="p", purpose_column="v", amount_column="a",
    )
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def _history(session, acc, profile_id):
    record_import(
        session, account_id=acc.id, account_name=acc.display_name, imported_count=1,
        duplicate_count=0, mapping_profile_id=profile_id,
    )
    session.commit()


def test_backfill_sets_unambiguous_profile_only(session):
    _prepare(session)
    p1, p2 = _profile(session, "A"), _profile(session, "B")
    unique = _account(session, "DE01")      # immer p1 -> eindeutig
    mixed = _account(session, "DE02")       # p1 und p2 -> mehrdeutig
    never = _account(session, "DE03")       # nie importiert
    legacy = _account(session, "DE04")      # Historie ohne Profil-Angabe (vor der Spalte)
    _history(session, unique, p1.id); _history(session, unique, p1.id)
    _history(session, mixed, p1.id); _history(session, mixed, p2.id)
    _history(session, legacy, None)

    assert backfill_default_mapping_profiles(session) == 1
    for acc in (unique, mixed, never, legacy):
        session.refresh(acc)
    assert unique.default_mapping_profile_id == p1.id
    assert mixed.default_mapping_profile_id is None
    assert never.default_mapping_profile_id is None
    assert legacy.default_mapping_profile_id is None


def test_backfill_runs_only_once_and_keeps_existing_default(session):
    _prepare(session)
    p1, p2 = _profile(session, "A"), _profile(session, "B")
    acc = _account(session, "DE01")
    _history(session, acc, p1.id)
    assert backfill_default_mapping_profiles(session) == 1
    # Nutzer leert das Standard-Mapping bewusst - ein weiterer Lauf darf es nicht neu setzen
    acc.default_mapping_profile_id = None
    session.add(acc); session.commit()
    assert backfill_default_mapping_profiles(session) == 0
    session.refresh(acc)
    assert acc.default_mapping_profile_id is None


def test_backfill_ignores_deleted_profile(session):
    _prepare(session)
    p1 = _profile(session, "A")
    acc = _account(session, "DE01")
    _history(session, acc, p1.id)
    session.delete(p1); session.commit()
    assert backfill_default_mapping_profiles(session) == 0


def test_record_import_still_prunes_to_max_entries(session):
    acc = _account(session, "DE01")
    for _ in range(MAX_ENTRIES + 3):
        _history(session, acc, None)
    assert len(session.exec(select(ImportHistoryEntry)).all()) == MAX_ENTRIES


def test_single_profile_is_assigned_to_all_accounts_without_default(session):
    _prepare(session)
    only = _profile(session, "Einziges")
    never, used = _account(session, "DE01"), _account(session, "DE02")
    _history(session, used, only.id)
    assert backfill_default_mapping_profiles(session) == 2
    for acc in (never, used):
        session.refresh(acc)
        assert acc.default_mapping_profile_id == only.id


def test_several_profiles_stay_unassigned_when_history_is_unclear(session):
    _prepare(session)
    _profile(session, "A"); _profile(session, "B")
    never = _account(session, "DE01")
    assert backfill_default_mapping_profiles(session) == 0
    session.refresh(never)
    assert never.default_mapping_profile_id is None


def test_single_profile_step_also_runs_after_history_step_was_already_done(session):
    _prepare(session)
    session.execute(text("INSERT INTO app_meta (key, value) VALUES ('default_mapping_backfill_done', '1')"))
    only = _profile(session, "Einziges")
    acc = _account(session, "DE01")
    assert backfill_default_mapping_profiles(session) == 1
    session.refresh(acc)
    assert acc.default_mapping_profile_id == only.id


def test_single_profile_step_runs_only_once(session):
    _prepare(session)
    only = _profile(session, "Einziges")
    acc = _account(session, "DE01")
    backfill_default_mapping_profiles(session)
    acc.default_mapping_profile_id = None
    session.add(acc); session.commit()
    assert backfill_default_mapping_profiles(session) == 0
    session.refresh(acc)
    assert acc.default_mapping_profile_id is None
    assert only.id is not None
