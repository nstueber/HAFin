"""Unit-Tests fuer app/services/backup.py (Export/Import-Kern, ohne HTTP/Playwright).

Deckt die reine Logik ab (Abhaengigkeiten, Ersetzungsplan, Export/Import-Rundlauf, defekte
Dateien, Reset) - die ausfuehrlichere End-to-End-Abdeckung (UI, Sicherheits-Backup-Download,
Ingress) bleibt Sache der Playwright-Suite (~/hafin-test-data/scripts/test_r13_backup.py etc.).
"""

from datetime import date

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Account, Category, CategoryBudget, Transaction, TransactionType
from app.services import backup as svc


def _fresh_engine():
    """Eine ZWEITE, leere In-Memory-Engine - fuer Tests, die einen Export aus einer befuellten
    Quelle in eine wirklich leere Zieldatenbank importieren (nicht dieselbe wie die ``session``-
    Fixture, sonst kollidieren z.B. IBAN-Unique-Constraints mit den Quelldaten)."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


# ---------------------------------------------------------------------------- with_dependencies


def test_with_dependencies_pulls_in_required_groups():
    assert set(svc.with_dependencies(["transactions"])) == {"accounts", "categories", "transactions"}
    assert set(svc.with_dependencies(["budgets"])) == {"categories", "budgets"}
    assert set(svc.with_dependencies(["accounts"])) == {"accounts"}


def test_with_dependencies_keeps_group_order_from_groups_constant():
    # "categorization_rules" haengt von "categories" ab, das VOR ihr in GROUPS steht -
    # with_dependencies() muss die kanonische Reihenfolge liefern, nicht Einfuegereihenfolge.
    assert svc.with_dependencies(["categorization_rules", "accounts"]) == [
        "accounts", "categories", "categorization_rules",
    ]


# ------------------------------------------------------------------------------- replace_plan


def test_replace_plan_categories_pulls_in_rules_budgets_and_transactions():
    counts = {
        "accounts": 2, "categories": 5, "mapping_profiles": 1, "categorization_rules": 3,
        "budgets": 2, "transactions": 100, "transaction_splits": 4, "rejected_transfer_pairs": 1,
        "recurring_ignores": 3,
    }
    plan = svc.replace_plan(["categories"], counts)
    assert plan["categories"] == 5
    assert plan["categorization_rules"] == 3  # zeigt auf Kategorien -> muss mit weg
    assert plan["budgets"] == 2
    assert plan["transactions"] == 100  # koennte auf geloeschte Kategorien zeigen -> muss mit weg
    assert plan["accounts"] == 0  # nicht ausgewaehlt -> bleibt
    assert plan["recurring_ignores"] == 3  # haengt an Konten/Buchungen -> faellt mit weg


def test_replace_plan_mapping_profiles_alone_touches_nothing_else():
    counts = {
        "accounts": 2, "categories": 5, "mapping_profiles": 1, "categorization_rules": 3,
        "budgets": 2, "transactions": 100, "transaction_splits": 4, "rejected_transfer_pairs": 1,
        "recurring_ignores": 3,
    }
    plan = svc.replace_plan(["mapping_profiles"], counts)
    assert plan["mapping_profiles"] == 1
    assert plan["transactions"] == 0
    assert plan["categories"] == 0


def test_target_is_empty():
    assert svc.target_is_empty({"accounts": 0, "transactions": 0})
    assert not svc.target_is_empty({"accounts": 1, "transactions": 0})
    assert not svc.target_is_empty({"accounts": 0, "transactions": 1})


# --------------------------------------------------------------------- Export/Import-Rundlauf


def _seed(session):
    acc = Account(iban="DE00111", display_name="Girokonto")
    session.add(acc)
    session.commit()
    session.refresh(acc)

    top = Category(name="Lebensmittel", type="ausgabe")
    session.add(top)
    session.commit()
    session.refresh(top)

    txn = Transaction(
        account_id=acc.id, booking_date=date(2026, 9, 1), payee="REWE", purpose="Einkauf",
        amount=-45.30, category_id=top.id, transaction_type=TransactionType.AUSGANG,
    )
    session.add(txn)
    session.add(CategoryBudget(category_id=top.id, monthly_amount=200.0))
    session.commit()
    return acc, top, txn


def test_build_export_and_round_trip_import_preserves_data(session):
    _seed(session)

    doc, counts = svc.build_export(session, svc.GROUPS)
    assert counts["accounts"] == 1
    assert counts["transactions"] == 1
    assert doc["meta"]["format"] == "haushaltsbuch-backup"

    raw = svc.dump_json(doc)
    parsed = svc.parse_backup(raw)
    assert parsed.problems == {}
    selected = svc.resolve_selection(parsed, svc.GROUPS)

    with Session(_fresh_engine()) as target:  # wirklich leere Zieldatenbank, nicht "session"
        report = svc.execute_import(target, parsed, selected, mode="empty")
        target.commit()

        assert report.imported["accounts"] == 1
        assert report.imported["transactions"] == 1
        imported_txn = target.exec(select(Transaction)).one()
        assert imported_txn.payee == "REWE"
        assert imported_txn.amount == -45.30
        imported_cat = target.exec(select(Category)).one()
        assert imported_cat.name == "Lebensmittel"
        assert imported_txn.category_id == imported_cat.id  # export_id-Referenz korrekt aufgeloest
        imported_budget = target.exec(select(CategoryBudget)).one()
        assert imported_budget.category_id == imported_cat.id


def test_build_export_without_any_valid_group_raises(session):
    # Leere Auswahl -> BackupError, bevor ueberhaupt eine Query gegen die Session laeuft.
    with pytest.raises(svc.BackupError):
        svc.build_export(session, [])


def test_resolve_selection_rejects_missing_dependency():
    # "transactions" ohne "categories" in der Datei -> Status "not ok" wegen fehlender Abhaengigkeit
    parsed = svc.ParsedBackup(meta={}, records={"accounts": [], "transactions": []})
    with pytest.raises(svc.BackupError):
        svc.resolve_selection(parsed, ["transactions"])


def test_resolve_selection_empty_selection_raises():
    parsed = svc.ParsedBackup(meta={}, records={})
    with pytest.raises(svc.BackupError):
        svc.resolve_selection(parsed, [])


# ------------------------------------------------------------------------- defekte Dateien


def test_parse_backup_rejects_invalid_json():
    with pytest.raises(svc.BackupError):
        svc.parse_backup(b"das ist kein JSON")


def test_parse_backup_flags_dangling_reference_as_problem():
    doc = {
        "meta": {"format": "haushaltsbuch-backup", "schema_version": 1},
        "categories": [{"export_id": "cat-1", "name": "Test", "system_key": None}],
        "accounts": [{"export_id": "acc-1", "iban": "DE00", "display_name": "Test"}],
        "transactions": [
            {
                "export_id": "t-1", "account": "acc-1", "category": "does-not-exist",
                "booking_date": "2026-09-01", "payee": "X", "amount": -1.0,
            }
        ],
    }
    parsed = svc.parse_backup(svc.dump_json(doc))
    assert parsed.problems.get("transactions"), "erwartete einen Problem-Eintrag fuer die haengende Referenz"


def test_parse_backup_wrong_format_marker_raises():
    doc = {"meta": {"format": "irgendwas-anderes", "schema_version": 1}}
    with pytest.raises(svc.BackupError):
        svc.parse_backup(svc.dump_json(doc))


# -------------------------------------------------------------------------------------- reset_all


def test_reset_all_deletes_everything_but_keeps_system_categories(session):
    from app.system_categories import get_or_create_system_category

    _seed(session)
    umbuchung = get_or_create_system_category(session, "umbuchung")

    deleted = svc.reset_all(session)

    assert deleted["accounts"] == 1
    assert deleted["transactions"] == 1
    assert session.exec(select(Account)).all() == []
    assert session.exec(select(Transaction)).all() == []
    # Systemkategorie bleibt erhalten (nicht Teil von target_counts()/Loeschung)
    remaining = session.exec(select(Category)).all()
    assert len(remaining) == 1
    assert remaining[0].id == umbuchung.id


# ------------------------------------------------------ delete_transactions_in_period (Runde 20)


def _account(session, iban="DE00"):
    acc = Account(iban=iban, display_name=iban)
    session.add(acc)
    session.commit()
    session.refresh(acc)
    return acc


def _txn(session, account, day, amount, counter_transaction_id=None, transaction_type=None):
    t = Transaction(
        account_id=account.id, booking_date=day, payee="x", amount=amount,
        transaction_type=transaction_type or TransactionType.AUSGANG,
        counter_transaction_id=counter_transaction_id,
    )
    session.add(t)
    session.commit()
    session.refresh(t)
    return t


def test_count_and_delete_transactions_in_period_respects_account_filter(session):
    acc1 = _account(session, "DE01")
    acc2 = _account(session, "DE02")
    _txn(session, acc1, date(2026, 9, 5), -10.0)
    _txn(session, acc1, date(2026, 9, 25), -20.0)
    _txn(session, acc2, date(2026, 9, 10), -30.0)
    _txn(session, acc1, date(2026, 8, 31), -1.0)  # ausserhalb des Zeitraums

    assert svc.count_transactions_in_period(session, date(2026, 9, 1), date(2026, 9, 30), None) == 3
    assert svc.count_transactions_in_period(session, date(2026, 9, 1), date(2026, 9, 30), acc1.id) == 2

    deleted = svc.delete_transactions_in_period(session, date(2026, 9, 1), date(2026, 9, 30), acc1.id)

    assert deleted["transactions"] == 2
    remaining = {t.booking_date for t in session.exec(select(Transaction)).all()}
    assert remaining == {date(2026, 9, 10), date(2026, 8, 31)}


def test_delete_transactions_in_period_unlinks_surviving_transfer_partner(session):
    acc1 = _account(session, "DE01")
    acc2 = _account(session, "DE02")
    inside = _txn(session, acc1, date(2026, 9, 5), -100.0, transaction_type=TransactionType.UMBUCHUNG)
    outside = _txn(session, acc2, date(2026, 10, 5), 100.0, transaction_type=TransactionType.UMBUCHUNG)
    inside.counter_transaction_id = outside.id
    outside.counter_transaction_id = inside.id
    outside.category_id = 999  # simuliert die feste "Umbuchung"-Kategorie
    session.add(inside)
    session.add(outside)
    session.commit()

    inside_id, outside_id = inside.id, outside.id
    svc.delete_transactions_in_period(session, date(2026, 9, 1), date(2026, 9, 30), None)

    # session.get() wuerde hier ObjectDeletedError werfen (das Test selbst haelt noch eine
    # abgelaufene Python-Referenz auf "inside") - eine frische Query gibt stattdessen sauber [] zurueck.
    assert session.exec(select(Transaction).where(Transaction.id == inside_id)).first() is None
    survivor = session.exec(select(Transaction).where(Transaction.id == outside_id)).one()
    assert survivor.counter_transaction_id is None
    assert survivor.transaction_type == TransactionType.EINGANG
    assert survivor.category_id is None


def test_delete_transactions_in_period_empty_range_is_a_no_op(session):
    _account(session, "DE01")
    deleted = svc.delete_transactions_in_period(session, date(2026, 9, 1), date(2026, 9, 30), None)
    assert deleted == {"transactions": 0, "transaction_splits": 0}


# ------------------------------------------------ Standard-Mapping je Konto + Ignorier-Liste (Runde 22)


def test_default_mapping_profile_survives_export_import_round_trip(session):
    from app.models import MappingProfile

    profile = MappingProfile(name="Sparkasse", date_column="d", payee_column="p", purpose_column="v", amount_column="a")
    session.add(profile)
    session.commit()
    session.refresh(profile)
    acc = Account(iban="DE00111", display_name="Giro", default_mapping_profile_id=profile.id)
    session.add(acc)
    session.add(Account(iban="DE00222", display_name="Ohne"))
    session.commit()

    doc, _counts = svc.build_export(session, ["accounts", "mapping_profiles"])
    parsed = svc.parse_backup(svc.dump_json(doc))
    assert parsed.problems == {}
    selected = svc.resolve_selection(parsed, ["accounts", "mapping_profiles"])

    with Session(_fresh_engine()) as target:
        svc.execute_import(target, parsed, selected, mode="empty")
        target.commit()
        imported = {a.display_name: a for a in target.exec(select(Account)).all()}
        imported_profile = target.exec(select(MappingProfile)).one()
        assert imported["Giro"].default_mapping_profile_id == imported_profile.id
        assert imported["Ohne"].default_mapping_profile_id is None


def test_default_mapping_profile_reference_is_dropped_without_profiles_group(session):
    from app.models import MappingProfile

    profile = MappingProfile(name="Sparkasse", date_column="d", payee_column="p", purpose_column="v", amount_column="a")
    session.add(profile)
    session.commit()
    session.refresh(profile)
    session.add(Account(iban="DE00111", display_name="Giro", default_mapping_profile_id=profile.id))
    session.commit()

    doc, _counts = svc.build_export(session, ["accounts", "mapping_profiles"])
    parsed = svc.parse_backup(svc.dump_json(doc))
    selected = svc.resolve_selection(parsed, ["accounts"])  # Profile bewusst nicht mitimportiert
    with Session(_fresh_engine()) as target:
        svc.execute_import(target, parsed, selected, mode="empty")
        target.commit()
        assert target.exec(select(Account)).one().default_mapping_profile_id is None


def test_reset_all_also_removes_recurring_ignores(session):
    from app.models import RecurringIgnore

    acc, _top, _txn = _seed(session)
    session.add(RecurringIgnore(account_id=acc.id, payee_key="netflix", sign=-1))
    session.commit()
    svc.reset_all(session)
    assert session.exec(select(RecurringIgnore)).all() == []


def test_replacing_mapping_profiles_clears_account_defaults(session):
    from app.models import MappingProfile

    profile = MappingProfile(name="Sparkasse", date_column="d", payee_column="p", purpose_column="v", amount_column="a")
    session.add(profile)
    session.commit()
    session.refresh(profile)
    acc = Account(iban="DE00111", display_name="Giro", default_mapping_profile_id=profile.id)
    session.add(acc)
    session.commit()
    svc._delete_existing(session, {"mapping_profiles"})
    session.commit()
    session.refresh(acc)
    assert acc.default_mapping_profile_id is None


def test_recurring_ignores_round_trip_and_requires_accounts(session):
    from app.models import RecurringIgnore

    acc, _top, _txn = _seed(session)
    session.add(RecurringIgnore(account_id=acc.id, payee_key="netflix", sign=-1))
    session.add(RecurringIgnore(account_id=acc.id, payee_key="arbeitgeber", sign=1))
    session.commit()

    assert svc.with_dependencies(["recurring_ignores"]) == ["accounts", "recurring_ignores"]
    doc, counts = svc.build_export(session, ["recurring_ignores"])
    assert counts["recurring_ignores"] == 2 and counts["accounts"] == 1
    parsed = svc.parse_backup(svc.dump_json(doc))
    assert parsed.problems == {}
    selected = svc.resolve_selection(parsed, ["recurring_ignores"])
    assert selected == ["accounts", "recurring_ignores"]

    with Session(_fresh_engine()) as target:
        report = svc.execute_import(target, parsed, selected, mode="empty")
        target.commit()
        assert report.imported["recurring_ignores"] == 2
        rows = {(r.payee_key, r.sign) for r in target.exec(select(RecurringIgnore)).all()}
        assert rows == {("netflix", -1), ("arbeitgeber", 1)}
        assert target.exec(select(RecurringIgnore)).first().account_id == target.exec(select(Account)).one().id


def test_recurring_ignores_without_accounts_in_file_is_a_problem():
    doc = {
        "meta": {"format": "haushaltsbuch-backup", "schema_version": 1},
        "recurring_ignores": [{"export_id": "r-1", "account": "acc-1", "payee_key": "netflix", "sign": -1}],
    }
    parsed = svc.parse_backup(svc.dump_json(doc))
    assert parsed.problems.get("recurring_ignores")
    assert not parsed.status("recurring_ignores")[0]


def test_recurring_ignores_invalid_sign_is_reported():
    doc = {
        "meta": {"format": "haushaltsbuch-backup", "schema_version": 1},
        "accounts": [{"export_id": "acc-1", "iban": "DE00", "display_name": "T"}],
        "recurring_ignores": [{"export_id": "r-1", "account": "acc-1", "payee_key": "x", "sign": 5}],
    }
    parsed = svc.parse_backup(svc.dump_json(doc))
    assert any("sign" in m for m in parsed.problems.get("recurring_ignores", []))


def test_old_backup_without_recurring_ignores_still_imports(session):
    _seed(session)
    doc, _ = svc.build_export(session, ["accounts"])
    assert "recurring_ignores" not in doc
    parsed = svc.parse_backup(svc.dump_json(doc))
    assert parsed.problems == {} and not parsed.present("recurring_ignores")
