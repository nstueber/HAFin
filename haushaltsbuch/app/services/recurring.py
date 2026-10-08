"""Erkennung wiederkehrender Zahlungen (Abos/Dauerauftraege) aus den vorhandenen Buchungen.

Ablauf (je Konto, Einnahmen und Ausgaben getrennt; Umbuchungen bleiben aussen vor):

1. **Gruppieren nach Auftraggeber** - erst ueber den "entzifferten" Namen (Kleinbuchstaben, ohne Ziffern/
   Satzzeichen), dann werden aehnliche Namen (``text_similarity`` >= ``PAYEE_THRESHOLD``) zusammengefuehrt.
   Dieselbe difflib-Heuristik wie bei "Aehnliche Zahlungen" (app/services/similarity.py), nur mit
   strengerer Schwelle, weil hier allein kurze Namen verglichen werden.
2. **Reihen bilden** - innerhalb einer Gruppe gehoert eine Buchung zu einer Reihe, wenn ihr Betrag um
   hoechstens ``max(AMOUNT_BAND_MIN, AMOUNT_BAND_REL * |letzter Betrag der Reihe|)`` vom letzten Betrag der
   Reihe abweicht. Das Band ist bewusst weiter als die Preisaenderungs-Schwelle, damit eine Preiserhoehung
   in derselben Reihe bleibt und erkannt werden kann.
3. **Rhythmus** - Median der Abstaende zwischen aufeinanderfolgenden Buchungen, zugeordnet zu
   woechentlich / monatlich / vierteljaehrlich / jaehrlich (je mit Toleranz in Tagen, siehe ``PERIODS``);
   mindestens ``MIN_OCCURRENCES`` Buchungen und mindestens ``MIN_REGULAR_SHARE`` der Abstaende muessen im
   Toleranzfenster liegen (ein ausgelassener Monat verwirft die Reihe nicht, Zufallstreffer schon).
4. **Hinweise** - "Betrag geaendert" und "Erwartete Zahlung blieb aus" (siehe ``_amount_change`` und
   ``_overdue_days``); eine Reihe, die seit mehr als zwei Perioden ausbleibt, gilt als beendet.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from sqlmodel import Session, select

from app.models import Account, Category, RecurringIgnore, Transaction, TransactionType
from app.services.category_tree import category_path
from app.services.similarity import text_similarity

MIN_OCCURRENCES = 3
PAYEE_THRESHOLD = 0.8
AMOUNT_BAND_REL = 0.25
AMOUNT_BAND_MIN = 2.0
MIN_REGULAR_SHARE = 0.75
# Preisaenderung: Abweichung des letzten Betrags vom bisher ueblichen (Median der bis zu drei
# vorherigen) um mindestens CHANGE_MIN_ABS Euro UND CHANGE_MIN_REL des ueblichen Betrags
CHANGE_MIN_ABS = 0.50
CHANGE_MIN_REL = 0.05


@dataclass(frozen=True)
class Period:
    key: str
    label: str
    min_days: int  # Toleranzfenster fuer den Abstand zweier Buchungen
    max_days: int
    nominal_days: int  # fuer "beendet" (zwei ausgefallene Perioden)
    grace_days: int  # so viele Tage nach dem erwarteten Datum gilt die Zahlung noch nicht als ausgeblieben
    months: int = 0  # >0: naechstes Datum per Kalendermonat, sonst nominal_days


PERIODS = (
    Period("weekly", "wöchentlich", 5, 9, 7, 3),
    Period("monthly", "monatlich", 26, 35, 30, 5, months=1),
    Period("quarterly", "vierteljährlich", 80, 100, 91, 7, months=3),
    Period("yearly", "jährlich", 350, 380, 365, 14, months=12),
)


@dataclass
class RecurringSeries:
    account_id: int
    account_name: str
    payee: str
    payee_key: str
    sign: int
    category: str
    period: Period
    count: int
    last_amount: float
    last_date: date
    next_expected: date
    usual_amount: float
    amount_changed: bool = False
    overdue_days: Optional[int] = None
    ended: bool = False
    ignored: bool = False
    member_keys: set = field(default_factory=set)
    members: list = field(default_factory=list)  # Buchungen der Reihe, aelteste zuerst
    categories_inconsistent: bool = False  # kategorisierte Buchungen der Reihe haben verschiedene Kategorien

    @property
    def first_id(self) -> Optional[int]:
        """ID der aeltesten Buchung - stabile Kennung der Reihe fuer die Detailansicht."""
        return self.members[0].id if self.members else None

    @property
    def needs_attention(self) -> bool:
        return not self.ended and not self.ignored and (self.amount_changed or self.overdue_days is not None)


def payee_key(text: str) -> str:
    """Normalisierter Auftraggeber: Kleinbuchstaben, ohne Ziffern/Satzzeichen, Leerraum zusammengefasst."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-zäöüß ]", " ", text.lower())).strip()


def _add_months(d: date, months: int) -> date:
    index = d.month - 1 + months
    year, month = d.year + index // 12, index % 12 + 1
    # Monatsende statt ungueltigem Datum (z.B. 31. + 1 Monat)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return d.replace(year=year, month=month, day=min(d.day, (nxt - timedelta(days=1)).day))


def _next_expected(last: date, period: Period) -> date:
    return _add_months(last, period.months) if period.months else last + timedelta(days=period.nominal_days)


def _detect_period(dates: list[date]) -> Optional[Period]:
    intervals = [(b - a).days for a, b in zip(dates, dates[1:])]
    if not intervals:
        return None
    median = statistics.median(intervals)
    for period in PERIODS:
        if period.min_days <= median <= period.max_days:
            regular = sum(1 for i in intervals if period.min_days <= i <= period.max_days)
            return period if regular / len(intervals) >= MIN_REGULAR_SHARE else None
    return None


def _amount_change(amounts: list[float]) -> tuple[bool, float]:
    """(geaendert?, ueblicher Betrag). Nur wenn die bis zu drei Betraege VOR dem letzten untereinander
    stabil sind - bei schwankenden Rechnungen (Strom, Telefon) gibt es keinen "ueblichen" Betrag, also
    auch keine Preiserhoehung. Nach der zweiten Buchung zum neuen Preis ist die Reihe nicht mehr
    "stabil davor" und der Hinweis verschwindet von selbst."""
    latest, previous = amounts[-1], amounts[-4:-1]
    usual = statistics.median(previous)
    threshold = max(CHANGE_MIN_ABS, CHANGE_MIN_REL * abs(usual))
    stable = all(abs(p - usual) < threshold for p in previous)
    changed = stable and round(abs(latest - usual), 2) >= threshold
    return changed, usual


def _overdue_days(next_expected: date, period: Period, today: date) -> tuple[Optional[int], bool]:
    """(Tage nach dem erwarteten Datum, beendet?) - ``None`` solange innerhalb der Karenz."""
    late = (today - next_expected).days
    if late <= period.grace_days:
        return None, False
    return late, late > 2 * period.nominal_days


def _cluster_payees(items: list[Transaction]) -> list[list[Transaction]]:
    by_key: dict[str, list[Transaction]] = defaultdict(list)
    for t in items:
        by_key[payee_key(t.payee or "") or payee_key(t.purpose or "")].append(t)
    keys = sorted(by_key, key=lambda k: -len(by_key[k]))
    clusters: list[tuple[str, list[Transaction]]] = []
    for key in keys:
        for rep, members in clusters:
            if key == rep or text_similarity(key, rep) >= PAYEE_THRESHOLD:
                members.extend(by_key[key])
                break
        else:
            clusters.append((key, list(by_key[key])))
    return [members for _rep, members in clusters if len(members) >= MIN_OCCURRENCES]


def _split_series(items: list[Transaction]) -> list[list[Transaction]]:
    series: list[list[Transaction]] = []
    for t in sorted(items, key=lambda x: (x.booking_date, x.id or 0)):
        best, best_diff = None, None
        for s in series:
            ref = s[-1].amount
            diff = abs(t.amount - ref)
            if diff <= max(AMOUNT_BAND_MIN, AMOUNT_BAND_REL * abs(ref)) and (best is None or diff < best_diff):
                best, best_diff = s, diff
        if best is None:
            series.append([t])
        else:
            best.append(t)
    return [s for s in series if len(s) >= MIN_OCCURRENCES]


def find_series(
    transactions: list[Transaction],
    account_names: dict[int, str],
    category_label,
    today: Optional[date] = None,
) -> list[RecurringSeries]:
    """Reine Erkennung ohne Datenbank (testbar). ``category_label(category_id) -> str``."""
    today = today or date.today()
    groups: dict[tuple[int, int], list[Transaction]] = defaultdict(list)
    for t in transactions:
        if t.transaction_type == TransactionType.UMBUCHUNG or not t.amount:
            continue
        groups[(t.account_id, 1 if t.amount > 0 else -1)].append(t)

    result: list[RecurringSeries] = []
    for (account_id, sign), items in groups.items():
        if len(items) < MIN_OCCURRENCES:
            continue
        for cluster in _cluster_payees(items):
            for members in _split_series(cluster):
                dates = [m.booking_date for m in members]
                period = _detect_period(dates)
                if period is None:
                    continue
                last = members[-1]
                amounts = [m.amount for m in members]
                changed, usual = _amount_change(amounts)
                next_expected = _next_expected(last.booking_date, period)
                overdue, ended = _overdue_days(next_expected, period, today)
                first_key = payee_key(members[0].payee or "") or payee_key(members[0].purpose or "")
                # Kategorie = die der juengsten Buchung MIT Kategorie (nicht zwingend der juengsten ueberhaupt);
                # unterscheiden sich die vergebenen Kategorien, wird die Reihe als uneinheitlich markiert
                categorized = [m.category_id for m in members if m.category_id is not None]
                latest_category = categorized[-1] if categorized else None
                result.append(
                    RecurringSeries(
                        account_id=account_id,
                        account_name=account_names.get(account_id, "–"),
                        payee=last.payee,
                        payee_key=first_key,
                        sign=sign,
                        category=category_label(latest_category),
                        categories_inconsistent=len(set(categorized)) > 1,
                        members=members,
                        period=period,
                        count=len(members),
                        last_amount=last.amount,
                        last_date=last.booking_date,
                        next_expected=next_expected,
                        usual_amount=usual if changed else last.amount,
                        amount_changed=changed,
                        overdue_days=overdue,
                        ended=ended,
                        member_keys={
                            payee_key(m.payee or "") or payee_key(m.purpose or "") for m in members
                        },
                    )
                )
    result.sort(key=lambda s: (not s.needs_attention, s.next_expected, s.payee.lower()))
    return result


def find_member_series(
    series: list[RecurringSeries], account_id: int, sign: int, first_id: int
) -> Optional[RecurringSeries]:
    return next(
        (s for s in series if s.account_id == account_id and s.sign == sign and s.first_id == first_id), None
    )


@dataclass(frozen=True)
class TwelveMonthSummary:
    total: float
    count: int
    months: int  # abgedeckter Zeitraum in Monaten (12, wenn die Reihe lang genug bekannt ist)
    partial: bool  # Reihe ist kuerzer als 12 Monate bekannt

    @property
    def label(self) -> str:
        if not self.partial:
            return "Betrag in den letzten 12 Monaten"
        unit = "Monat" if self.months == 1 else "Monaten"
        return f"Betrag in den letzten {self.months} {unit} (seit Erkennung)"


def twelve_month_summary(series: RecurringSeries, today: Optional[date] = None) -> TwelveMonthSummary:
    """Summe der Reihe in den letzten 12 Monaten (von heute zurueck; Buchungen nach heute zaehlen nicht).
    Ist die Reihe erst seit kuerzerer Zeit bekannt (aelteste Buchung jung), steht der tatsaechlich
    abgedeckte Zeitraum im Label."""
    today = today or date.today()
    window_start = _add_months(today, -12)
    in_window = [m for m in series.members if window_start < m.booking_date <= today]
    first = series.members[0].booking_date
    partial = first > window_start
    months = max(1, round((today - first).days / 30.44)) if partial else 12
    return TwelveMonthSummary(
        total=round(sum(m.amount for m in in_window), 2), count=len(in_window), months=months, partial=partial
    )


def detect(session: Session, today: Optional[date] = None) -> list[RecurringSeries]:
    """Alle erkannten Reihen inkl. Markierung ignorierter (``ignored``) aus der Datenbank."""
    transactions = session.exec(select(Transaction)).all()
    accounts = {a.id: a.display_name for a in session.exec(select(Account)).all()}
    categories = {c.id: c for c in session.exec(select(Category)).all()}

    def label(category_id: Optional[int]) -> str:
        category = categories.get(category_id) if category_id else None
        return category_path(category, categories) if category else "Unkategorisiert"

    series = find_series(transactions, accounts, label, today)
    ignores = defaultdict(set)
    for ig in session.exec(select(RecurringIgnore)).all():
        ignores[(ig.account_id, ig.sign)].add(ig.payee_key)
    for s in series:
        s.ignored = bool(ignores[(s.account_id, s.sign)] & s.member_keys)
    return series


def attention_count(session: Session, today: Optional[date] = None) -> int:
    """Anzahl offener Hinweise (Betrag geaendert / Zahlung ausgeblieben) - Badge in der Navigation."""
    return sum(1 for s in detect(session, today) if s.needs_attention)
