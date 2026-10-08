"""Unit-Tests fuer die Erkennung wiederkehrender Zahlungen (app/services/recurring.py)."""

from datetime import date, timedelta

from app.models import Transaction, TransactionType
from app.services import recurring

_ID = iter(range(1, 100000))


def _t(day, payee, amount, account_id=1, kind=None):
    return Transaction(
        id=next(_ID), account_id=account_id, booking_date=day, payee=payee, amount=amount,
        transaction_type=kind or (TransactionType.EINGANG if amount > 0 else TransactionType.AUSGANG),
    )


_CATEGORIES = {1: "Abos › Streaming", 2: "Freizeit"}


def _find(txns, today):
    return recurring.find_series(
        txns, {1: "Giro", 2: "Spar"}, lambda cid: _CATEGORIES.get(cid, "Unkategorisiert"), today
    )


def _monthly(payee, amounts, start=date(2026, 1, 3), account_id=1):
    return [_t(recurring._add_months(start, i), payee, a, account_id) for i, a in enumerate(amounts)]


def test_monthly_series_detected_with_next_expected():
    txns = _monthly("Netflix", [-12.99] * 4)
    for t in txns:
        t.category_id = 1
    (s,) = _find(txns, date(2026, 5, 1))
    assert s.period.key == "monthly" and s.count == 4
    assert s.last_date == date(2026, 4, 3) and s.next_expected == date(2026, 5, 3)
    assert s.category == "Abos › Streaming" and s.account_name == "Giro"
    assert not s.amount_changed and s.overdue_days is None and not s.needs_attention


def test_two_occurrences_are_not_enough():
    assert _find(_monthly("Netflix", [-12.99] * 2), date(2026, 3, 1)) == []


def test_all_periods_detected():
    weekly = [_t(date(2026, 1, 1) + timedelta(days=7 * i), "Kurs", -10.0) for i in range(4)]
    quarterly = _monthly("Versicherung", [-50.0] * 3, start=date(2025, 1, 15))
    quarterly = [_t(recurring._add_months(date(2025, 1, 15), 3 * i), "Versicherung", -50.0) for i in range(3)]
    yearly = [_t(date(2023 + i, 6, 1), "Domain", -15.0) for i in range(3)]
    found = {s.payee: s.period.key for s in _find(weekly + quarterly + yearly, date(2026, 1, 20))}
    assert found == {"Kurs": "weekly", "Versicherung": "quarterly", "Domain": "yearly"}


def test_irregular_booking_dates_are_not_recurring():
    days = [date(2026, 1, 2), date(2026, 1, 9), date(2026, 3, 30), date(2026, 4, 2), date(2026, 7, 21)]
    assert _find([_t(d, "Spende", -20.0) for d in days], date(2026, 8, 1)) == []


def test_skipped_month_does_not_break_series():
    txns = [_t(d, "Fitness", -30.0) for d in (date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5),
                                              date(2026, 5, 5), date(2026, 6, 5), date(2026, 7, 5))]
    (s,) = _find(txns, date(2026, 7, 10))
    assert s.period.key == "monthly" and s.count == 6


def test_similar_payee_names_are_grouped_and_very_different_amounts_split():
    txns = [_t(date(2026, 1, 2), "REWE Markt 123", -50.0), _t(date(2026, 2, 2), "REWE Markt 456", -52.0),
            _t(date(2026, 3, 2), "REWE Markt 789", -49.0)]
    (s,) = _find(txns, date(2026, 3, 20))
    assert s.count == 3
    # gleicher Auftraggeber, aber voellig anderer Betrag -> eigene (zu kurze) Reihe, nicht mitgezaehlt
    txns.append(_t(date(2026, 3, 20), "REWE Markt 123", -400.0))
    (s,) = _find(txns, date(2026, 3, 25))
    assert s.count == 3


def test_income_and_expense_are_separate_and_transfers_ignored():
    inc = _monthly("Arbeitgeber", [2500.0] * 3)
    exp = _monthly("Arbeitgeber", [-20.0] * 3)
    transfers = [_t(recurring._add_months(date(2026, 1, 4), i), "Sparkonto", -100.0, kind=TransactionType.UMBUCHUNG) for i in range(3)]
    found = _find(inc + exp + transfers, date(2026, 3, 20))
    assert sorted(s.sign for s in found) == [-1, 1]


def test_series_is_per_account():
    a = _monthly("Strom", [-80.0] * 3, account_id=1)
    b = _monthly("Strom", [-80.0] * 2, account_id=2)  # nur 2 Buchungen auf Konto 2
    found = _find(a + b, date(2026, 3, 20))
    assert [s.account_id for s in found] == [1]


def test_amount_change_flagged_once_then_disappears():
    first_increase = _monthly("Netflix", [-12.99, -12.99, -12.99, -14.99])
    (s,) = _find(first_increase, date(2026, 4, 10))
    assert s.amount_changed and s.usual_amount == -12.99 and s.last_amount == -14.99 and s.needs_attention
    second_booking = _monthly("Netflix", [-12.99, -12.99, -12.99, -14.99, -14.99])
    (s,) = _find(second_booking, date(2026, 5, 10))
    assert not s.amount_changed


def test_small_deviation_is_tolerated_and_varying_bills_never_flag():
    (s,) = _find(_monthly("Miete", [-800.0, -800.0, -800.0, -820.0]), date(2026, 4, 10))
    assert not s.amount_changed  # 2,5 % < 5 %
    (s,) = _find(_monthly("Telefon", [-30.0, -35.0, -28.5, -33.0]), date(2026, 4, 10))
    assert not s.amount_changed  # schwankende Rechnung: kein "ueblicher" Betrag
    (s,) = _find(_monthly("App", [-0.99, -0.99, -0.99, -1.49]), date(2026, 4, 10))
    assert s.amount_changed  # +0,50 EUR und > 5 %


def test_missing_payment_flag_after_grace_period_and_ended_after_two_periods():
    txns = _monthly("Netflix", [-12.99] * 3)  # letzte Buchung 3.3., erwartet 3.4.
    (s,) = _find(txns, date(2026, 4, 8))
    assert s.overdue_days is None  # 5 Tage Karenz
    (s,) = _find(txns, date(2026, 4, 9))
    assert s.overdue_days == 6 and s.needs_attention and not s.ended
    (s,) = _find(txns, date(2026, 8, 1))
    assert s.ended and not s.needs_attention


def test_month_end_clamps_next_expected():
    assert recurring._add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert recurring._add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)


def _categorized(categories):
    txns = _monthly("Netflix", [-12.99] * len(categories))
    for t, cid in zip(txns, categories):
        t.category_id = cid
    return txns


def test_category_is_that_of_latest_categorized_booking_not_latest_booking():
    (s,) = _find(_categorized([1, 1, 1, None]), date(2026, 4, 10))
    assert s.category == "Abos › Streaming"  # juengste Buchung unkategorisiert -> trotzdem die Reihe-Kategorie
    assert not s.categories_inconsistent  # unkategorisierte Buchungen zaehlen nicht als uneinheitlich


def test_series_without_any_category_stays_uncategorized():
    (s,) = _find(_categorized([None, None, None]), date(2026, 3, 10))
    assert s.category == "Unkategorisiert" and not s.categories_inconsistent


def test_mixed_categories_are_flagged_and_use_latest_categorized():
    (s,) = _find(_categorized([1, 1, 2, None]), date(2026, 4, 10))
    assert s.categories_inconsistent and s.category == "Freizeit"


def test_series_members_and_stable_first_id():
    txns = _categorized([1, 1, 1])
    (s,) = _find(txns, date(2026, 3, 10))
    assert [m.id for m in s.members] == [t.id for t in txns]
    assert s.first_id == txns[0].id
    assert recurring.find_member_series([s], 1, -1, txns[0].id) is s
    assert recurring.find_member_series([s], 1, 1, txns[0].id) is None


def test_twelve_month_summary_full_year():
    txns = _monthly("Netflix", [-10.0] * 14, start=date(2025, 1, 3))  # 14 Monate Historie
    (s,) = _find(txns, date(2026, 2, 20))
    summary = recurring.twelve_month_summary(s, date(2026, 2, 20))
    assert not summary.partial and summary.label == "Betrag in den letzten 12 Monaten"
    # Fenster (20.2.2025, 20.2.2026]: Buchungen vom 3.3.2025 bis 3.2.2026 = 12 Stueck
    assert summary.count == 12 and summary.total == -120.0


def test_twelve_month_summary_short_series_names_covered_period():
    txns = _monthly("Netflix", [-10.0] * 7, start=date(2026, 1, 3))
    (s,) = _find(txns, date(2026, 8, 10))
    summary = recurring.twelve_month_summary(s, date(2026, 8, 10))
    assert summary.partial and summary.months == 7 and summary.count == 7 and summary.total == -70.0
    assert summary.label == "Betrag in den letzten 7 Monaten (seit Erkennung)"


def test_twelve_month_summary_ignores_future_bookings():
    txns = _monthly("Netflix", [-10.0] * 4, start=date(2026, 1, 3))
    (s,) = _find(txns, date(2026, 3, 20))
    summary = recurring.twelve_month_summary(s, date(2026, 3, 20))
    assert summary.count == 3 and summary.total == -30.0  # 3.4. liegt nach "heute"
