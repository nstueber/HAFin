"""Automatische Kategorisierungsregeln: Laden, Abgleich und Anwendung.

Abgleich: ohne Beachtung von Gross-/Kleinschreibung und ohne Leerraum am Anfang/Ende des Feldes;
mehrfache Leerzeichen im Bankverwendungszweck werden vor dem Vergleich zu einem zusammengefasst
(Bank-CSVs fuellen Felder oft mit Leerzeichen auf). Es gewinnt immer die erste passende Regel in
Prioritaetsreihenfolge (``position`` aufsteigend).
"""

import re
from dataclasses import dataclass
from typing import Iterable, Optional

from sqlmodel import Session, select

from app.models import (
    RULE_FIELDS,
    RULE_OPERATORS,
    CategorizationRule,
    Transaction,
    TransactionType,
)


def normalize_text(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def load_rules(session: Session) -> list[CategorizationRule]:
    """Alle Regeln in Prioritaetsreihenfolge (oberste zuerst)."""
    return list(
        session.exec(
            select(CategorizationRule).order_by(CategorizationRule.position, CategorizationRule.id)
        ).all()
    )


def rule_matches(rule: CategorizationRule, payee: Optional[str], purpose: Optional[str]) -> bool:
    haystack = normalize_text(purpose if rule.field == "purpose" else payee)
    needle = normalize_text(rule.value)
    if not needle:
        return False  # eine leere Regel darf nie alles treffen
    if rule.operator == "equals":
        return haystack == needle
    if rule.operator == "starts_with":
        return haystack.startswith(needle)
    return needle in haystack  # "contains" (Standard)


def find_matching_rule(
    rules: Iterable[CategorizationRule], payee: Optional[str], purpose: Optional[str]
) -> Optional[CategorizationRule]:
    for rule in rules:
        if rule_matches(rule, payee, purpose):
            return rule
    return None


@dataclass
class RuleHit:
    """Ein Treffer der rueckwirkenden Anwendung: diese Buchung wuerde von dieser Regel erfasst."""

    txn: Transaction
    rule: CategorizationRule


def find_rule_hits(session: Session) -> tuple[list[RuleHit], int]:
    """Treffer der Regeln auf bestehende UNKATEGORISIERTE Buchungen (Umbuchungen ausgenommen).

    Rueckgabe: (Treffer, Anzahl der unkategorisierten Buchungen insgesamt). Eine Buchung, die bereits
    genau den Vorschlag traegt, den eine Vorschlags-Regel setzen wuerde, ist kein Treffer (kein Effekt)."""
    txns = session.exec(
        select(Transaction)
        .where(
            Transaction.category_id.is_(None),
            Transaction.transaction_type != TransactionType.UMBUCHUNG,
        )
        .order_by(Transaction.booking_date.desc(), Transaction.id.desc())
    ).all()
    rules = load_rules(session)
    hits: list[RuleHit] = []
    for txn in txns:
        rule = find_matching_rule(rules, txn.payee, txn.purpose)
        if rule is None:
            continue
        if rule.mode == "suggest" and txn.suggested_category_id == rule.category_id:
            continue
        hits.append(RuleHit(txn, rule))
    return hits, len(txns)


def apply_rule_to_transaction(txn: Transaction, rule: CategorizationRule) -> None:
    """Setzt je nach Regel-Modus die Kategorie fest oder hinterlegt nur einen Vorschlag."""
    if rule.mode == "suggest":
        txn.suggested_category_id = rule.category_id
    else:
        txn.category_id = rule.category_id
        txn.suggested_category_id = None


def apply_selected_hits(session: Session, pairs: Iterable[tuple[int, int]]) -> dict:
    """Wendet vom Nutzer ausgewaehlte Treffer an (Paare Buchungs-ID, Regel-ID) - nach erneuter Pruefung:
    die Buchung muss noch unkategorisiert sein und dieselbe Regel muss weiterhin als erste passen
    (zwischen Vorschau und Bestaetigen koennen sich Buchungen/Regeln geaendert haben). Commit macht der Aufrufer.
    Rueckgabe: Zaehler ``assigned`` / ``suggested`` / ``skipped``."""
    rules = load_rules(session)
    result = {"assigned": 0, "suggested": 0, "skipped": 0}
    for txn_id, rule_id in pairs:
        txn = session.get(Transaction, txn_id)
        if (
            txn is None
            or txn.category_id is not None
            or txn.transaction_type == TransactionType.UMBUCHUNG
        ):
            result["skipped"] += 1
            continue
        rule = find_matching_rule(rules, txn.payee, txn.purpose)
        if rule is None or rule.id != rule_id:
            result["skipped"] += 1
            continue
        apply_rule_to_transaction(txn, rule)
        session.add(txn)
        result["suggested" if rule.mode == "suggest" else "assigned"] += 1
    return result


def describe_rule(rule: CategorizationRule) -> str:
    return f"{RULE_FIELDS.get(rule.field, rule.field)} {RULE_OPERATORS.get(rule.operator, rule.operator)}"
