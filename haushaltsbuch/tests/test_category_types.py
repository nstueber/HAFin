"""Unit-Tests fuer app/services/category_types.py (Vererbung, Vorzeichen-Hinweis, Migration)."""

from datetime import date

from app.models import Category, Transaction, TransactionSplit, UMBUCHUNG_KEY
from app.services import category_types as svc


def _cat(session, name, type_=None, parent_id=None, system_key=None):
    c = Category(name=name, type=type_, parent_id=parent_id, system_key=system_key)
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


def _txn(session, category_id, amount):
    t = Transaction(
        account_id=1, booking_date=date(2026, 9, 1), payee="x", amount=amount, category_id=category_id,
        transaction_type="ausgang" if amount < 0 else "eingang",
    )
    session.add(t)
    session.commit()


# -------------------------------------------------------------------------------- top_level_of


def test_top_level_of_returns_self_for_top_level_category():
    top = Category(id=1, name="Top", parent_id=None)
    assert svc.top_level_of(top, {1: top}) is top


def test_top_level_of_returns_parent_for_sub_category():
    top = Category(id=1, name="Top", parent_id=None)
    sub = Category(id=2, name="Sub", parent_id=1)
    assert svc.top_level_of(sub, {1: top, 2: sub}) is top


def test_top_level_of_none_category_is_none():
    assert svc.top_level_of(None, {}) is None


# -------------------------------------------------------------------------------- effective_type


def test_effective_type_top_level_returns_own_type():
    top = Category(id=1, name="Top", type="ausgabe")
    assert svc.effective_type(top, {1: top}) == "ausgabe"


def test_effective_type_sub_category_inherits_parent_type():
    top = Category(id=1, name="Top", type="einnahme")
    sub = Category(id=2, name="Sub", parent_id=1)
    by_id = {1: top, 2: sub}
    assert svc.effective_type(sub, by_id) == "einnahme"


def test_effective_type_umbuchung_is_always_none_even_with_a_type_set():
    umbuchung = Category(id=1, name="Umbuchung", type="einnahme", system_key=UMBUCHUNG_KEY)
    assert svc.effective_type(umbuchung, {1: umbuchung}) is None


def test_effective_type_invalid_or_missing_type_is_none():
    top = Category(id=1, name="Top", type=None)
    assert svc.effective_type(top, {1: top}) is None
    top.type = "quatsch"
    assert svc.effective_type(top, {1: top}) is None


def test_effective_type_none_category_is_none():
    assert svc.effective_type(None, {}) is None


# --------------------------------------------------------------------------- sign_mismatch_hint


def test_sign_mismatch_hint_expense_with_positive_amount():
    assert svc.sign_mismatch_hint(5.0, "ausgabe") == "Ungewöhnlich: positiver Betrag in einer Ausgaben-Kategorie"


def test_sign_mismatch_hint_income_with_negative_amount():
    assert svc.sign_mismatch_hint(-5.0, "einnahme") == "Ungewöhnlich: negativer Betrag in einer Einnahmen-Kategorie"


def test_sign_mismatch_hint_matching_sign_or_no_type_is_none():
    assert svc.sign_mismatch_hint(-5.0, "ausgabe") is None
    assert svc.sign_mismatch_hint(5.0, "einnahme") is None
    assert svc.sign_mismatch_hint(5.0, None) is None
    assert svc.sign_mismatch_hint(-5.0, None) is None


# --------------------------------------------------------------------------- category_sign_hint


def test_category_sign_hint_without_category_id_is_none():
    assert svc.category_sign_hint(5.0, None, {}) is None


def test_category_sign_hint_unknown_category_id_is_none():
    assert svc.category_sign_hint(5.0, 999, {}) is None


def test_category_sign_hint_delegates_to_effective_type(session):
    top = _cat(session, "Ausgaben", type_="ausgabe")
    by_id = {top.id: top}
    assert svc.category_sign_hint(5.0, top.id, by_id) is not None
    assert svc.category_sign_hint(-5.0, top.id, by_id) is None


# ----------------------------------------------------------------------- backfill_category_types


def test_backfill_majority_by_count_wins_over_sum(session):
    # 2x +1 (Einnahme) vs. 1x -500 (Ausgabe): Mehrheit nach ANZAHL, nicht nach Summe
    cat = _cat(session, "MehrheitEinnahme")
    _txn(session, cat.id, 1.0)
    _txn(session, cat.id, 1.0)
    _txn(session, cat.id, -500.0)

    result = svc.backfill_category_types(session)
    session.refresh(cat)

    assert cat.type == "einnahme"
    assert result == {"einnahme": 1, "ausgabe": 0, "ausgabe_ohne_buchungen": 0}


def test_backfill_tie_falls_back_to_net_sum(session):
    cat = _cat(session, "Unentschieden")
    _txn(session, cat.id, 30.0)
    _txn(session, cat.id, -10.0)  # 1 gegen 1, Summe positiv -> einnahme

    svc.backfill_category_types(session)
    session.refresh(cat)

    assert cat.type == "einnahme"


def test_backfill_no_transactions_falls_back_to_ausgabe(session):
    cat = _cat(session, "Leer")

    result = svc.backfill_category_types(session)
    session.refresh(cat)

    assert cat.type == "ausgabe"
    assert result["ausgabe_ohne_buchungen"] == 1


def test_backfill_never_overwrites_an_already_set_type(session):
    cat = _cat(session, "SchonGesetzt", type_="einnahme")
    _txn(session, cat.id, -1000.0)  # wuerde eigentlich "ausgabe" ergeben

    svc.backfill_category_types(session)
    session.refresh(cat)

    assert cat.type == "einnahme"  # unveraendert


def test_backfill_ignores_umbuchung_system_category(session):
    umb = _cat(session, "Umbuchung", system_key=UMBUCHUNG_KEY)

    svc.backfill_category_types(session)
    session.refresh(umb)

    assert umb.type is None


def test_backfill_counts_transaction_splits_of_a_sub_category(session):
    top = _cat(session, "Top")
    sub = _cat(session, "Sub", parent_id=top.id)
    host = Transaction(account_id=1, booking_date=date(2026, 9, 1), payee="x", amount=-10.0, transaction_type="ausgang")
    session.add(host)
    session.commit()
    session.refresh(host)
    session.add(TransactionSplit(transaction_id=host.id, amount=7.0, category_id=sub.id))
    session.commit()

    svc.backfill_category_types(session)
    session.refresh(top)

    assert top.type == "einnahme"  # der Split-Betrag (+7) zaehlt auf die Oberkategorie ein


def test_backfill_is_idempotent_second_call_changes_nothing(session):
    cat = _cat(session, "X")
    _txn(session, cat.id, -5.0)

    first = svc.backfill_category_types(session)
    second = svc.backfill_category_types(session)  # kein Ziel mehr uebrig (type schon gesetzt)

    assert first == {"einnahme": 0, "ausgabe": 1, "ausgabe_ohne_buchungen": 0}
    assert second == {"einnahme": 0, "ausgabe": 0, "ausgabe_ohne_buchungen": 0}
