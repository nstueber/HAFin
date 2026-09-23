"""Unit-Tests fuer app/services/rules.py (Regel-Abgleich, rueckwirkende Anwendung)."""

from datetime import date

from app.models import Account, Category, CategorizationRule, Transaction, TransactionType
from app.services import rules as svc


def _account(session):
    acc = Account(iban="DE00", display_name="Test")
    session.add(acc)
    session.commit()
    session.refresh(acc)
    return acc


def _category(session, name="Kat"):
    cat = Category(name=name)
    session.add(cat)
    session.commit()
    session.refresh(cat)
    return cat


def _rule(session, position, field, operator, value, category_id, mode="assign"):
    rule = CategorizationRule(
        position=position, field=field, operator=operator, value=value,
        category_id=category_id, mode=mode,
    )
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


def _txn(session, account, payee, purpose=None, amount=-10.0, category_id=None,
          txn_type=TransactionType.AUSGANG, suggested_category_id=None):
    txn = Transaction(
        account_id=account.id, booking_date=date(2026, 9, 1), payee=payee, purpose=purpose,
        amount=amount, category_id=category_id, transaction_type=txn_type,
        suggested_category_id=suggested_category_id,
    )
    session.add(txn)
    session.commit()
    session.refresh(txn)
    return txn


# ---------------------------------------------------------------- normalize_text / rule_matches


def test_normalize_text_collapses_whitespace_strips_and_casefolds():
    assert svc.normalize_text("  REWE   Markt \n") == "rewe markt"
    assert svc.normalize_text(None) == ""
    assert svc.normalize_text("") == ""


def test_rule_matches_contains_is_case_insensitive_and_field_selects_payee_or_purpose():
    rule_purpose = CategorizationRule(field="purpose", operator="contains", value="miete", category_id=1)
    assert svc.rule_matches(rule_purpose, payee="Vermieter", purpose="Miete September")
    assert not svc.rule_matches(rule_purpose, payee="Miete GmbH", purpose="Sonstiges")  # falsches Feld

    rule_payee = CategorizationRule(field="payee", operator="contains", value="REWE", category_id=1)
    assert svc.rule_matches(rule_payee, payee="rewe markt gmbh", purpose="egal")


def test_rule_matches_starts_with_and_equals():
    starts = CategorizationRule(field="payee", operator="starts_with", value="Amazon", category_id=1)
    assert svc.rule_matches(starts, payee="Amazon EU SARL", purpose=None)
    assert not svc.rule_matches(starts, payee="Not Amazon", purpose=None)

    equals = CategorizationRule(field="payee", operator="equals", value="Kino", category_id=1)
    assert svc.rule_matches(equals, payee="Kino", purpose=None)
    assert not svc.rule_matches(equals, payee="Kino Sternenpalast", purpose=None)


def test_rule_matches_whitespace_is_collapsed_before_comparing():
    rule = CategorizationRule(field="purpose", operator="equals", value="Kartenzahlung REWE", category_id=1)
    assert svc.rule_matches(rule, payee=None, purpose="  Kartenzahlung   REWE  ")


def test_rule_matches_empty_value_never_matches():
    rule = CategorizationRule(field="purpose", operator="contains", value="   ", category_id=1)
    assert not svc.rule_matches(rule, payee="irrelevant", purpose="irrelevant")


# ---------------------------------------------------------------------------- find_matching_rule


def test_find_matching_rule_returns_first_match_in_priority_order():
    r1 = CategorizationRule(position=1, field="purpose", operator="contains", value="REWE", category_id=1)
    r2 = CategorizationRule(position=2, field="payee", operator="starts_with", value="Amazon", category_id=2)
    # "Amazon Prime" enthaelt REWE-Gutschein im Zweck -> Regel 1 (hoehere Prioritaet) gewinnt
    assert svc.find_matching_rule([r1, r2], payee="Amazon Prime", purpose="REWE Gutschein") is r1
    assert svc.find_matching_rule([r1, r2], payee="Amazon EU", purpose="Bestellung") is r2
    assert svc.find_matching_rule([r1, r2], payee="Sonstiges", purpose="nichts") is None


# ------------------------------------------------------------------------------- find_rule_hits


def test_find_rule_hits_excludes_categorized_and_umbuchung(session):
    acc = _account(session)
    cat = _category(session, "Lebensmittel")
    _rule(session, 1, "payee", "contains", "REWE", cat.id)
    hit_txn = _txn(session, acc, "REWE Markt")
    _txn(session, acc, "REWE bereits kategorisiert", category_id=cat.id)  # bereits kategorisiert -> kein Treffer
    _txn(session, acc, "REWE Umbuchung", txn_type=TransactionType.UMBUCHUNG)  # Umbuchung -> kein Treffer
    _txn(session, acc, "Ohne Regel")

    hits, total_uncategorized = svc.find_rule_hits(session)

    assert total_uncategorized == 2  # "REWE Markt" + "Ohne Regel" (Umbuchung zaehlt nicht mit)
    assert [h.txn.id for h in hits] == [hit_txn.id]


def test_find_rule_hits_suggest_mode_no_hit_if_suggestion_already_set(session):
    acc = _account(session)
    cat = _category(session, "Freizeit")
    _rule(session, 1, "payee", "contains", "Kino", cat.id, mode="suggest")
    already_suggested = _txn(session, acc, "Kino Sternenpalast", suggested_category_id=cat.id)
    not_yet_suggested = _txn(session, acc, "Kino Palast", suggested_category_id=None)

    hits, _ = svc.find_rule_hits(session)

    assert already_suggested.id not in [h.txn.id for h in hits]
    assert not_yet_suggested.id in [h.txn.id for h in hits]


# --------------------------------------------------------------------- apply_rule_to_transaction


def test_apply_rule_to_transaction_assign_mode_sets_category_and_clears_suggestion(session):
    acc = _account(session)
    cat = _category(session)
    txn = _txn(session, acc, "X", suggested_category_id=999)
    rule = CategorizationRule(field="payee", operator="contains", value="X", category_id=cat.id, mode="assign")

    svc.apply_rule_to_transaction(txn, rule)

    assert txn.category_id == cat.id
    assert txn.suggested_category_id is None


def test_apply_rule_to_transaction_suggest_mode_only_sets_suggestion(session):
    acc = _account(session)
    cat = _category(session)
    txn = _txn(session, acc, "X")
    rule = CategorizationRule(field="payee", operator="contains", value="X", category_id=cat.id, mode="suggest")

    svc.apply_rule_to_transaction(txn, rule)

    assert txn.category_id is None
    assert txn.suggested_category_id == cat.id


# ------------------------------------------------------------------------- apply_selected_hits


def test_apply_selected_hits_applies_and_reports_assigned_and_suggested(session):
    acc = _account(session)
    cat_assign = _category(session, "Ausgabe")
    cat_suggest = _category(session, "Vorschlag")
    _rule(session, 1, "payee", "contains", "REWE", cat_assign.id, mode="assign")
    _rule(session, 2, "payee", "contains", "Kino", cat_suggest.id, mode="suggest")
    t1 = _txn(session, acc, "REWE Markt")
    t2 = _txn(session, acc, "Kino Palast")

    result = svc.apply_selected_hits(session, [(t1.id, 1), (t2.id, 2)])
    session.commit()

    assert result == {"assigned": 1, "suggested": 1, "skipped": 0}
    session.refresh(t1)
    session.refresh(t2)
    assert t1.category_id == cat_assign.id
    assert t2.suggested_category_id == cat_suggest.id


def test_apply_selected_hits_skips_already_categorized_umbuchung_and_stale_rule(session):
    acc = _account(session)
    cat = _category(session)
    rule = _rule(session, 1, "payee", "contains", "X", cat.id)
    already_categorized = _txn(session, acc, "X1", category_id=cat.id)
    umbuchung = _txn(session, acc, "X2", txn_type=TransactionType.UMBUCHUNG)
    missing = 999999

    result = svc.apply_selected_hits(
        session,
        [(already_categorized.id, rule.id), (umbuchung.id, rule.id), (missing, rule.id)],
    )

    assert result == {"assigned": 0, "suggested": 0, "skipped": 3}


def test_apply_selected_hits_skips_when_rule_no_longer_first_match(session):
    acc = _account(session)
    cat_a = _category(session, "A")
    cat_b = _category(session, "B")
    rule_a = _rule(session, 1, "payee", "contains", "REWE", cat_a.id)
    rule_b = _rule(session, 2, "payee", "contains", "REWE", cat_b.id)
    txn = _txn(session, acc, "REWE Markt")

    # In der Vorschau war evtl. rule_b markiert, mittlerweile passt (Prioritaet) rule_a zuerst
    result = svc.apply_selected_hits(session, [(txn.id, rule_b.id)])

    assert result == {"assigned": 0, "suggested": 0, "skipped": 1}


# ---------------------------------------------------------------------------------- describe_rule


def test_describe_rule_uses_german_labels():
    rule = CategorizationRule(field="payee", operator="starts_with", value="Amazon", category_id=1)
    assert svc.describe_rule(rule) == "Auftraggeber/Empfänger beginnt mit"
