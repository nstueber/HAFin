"""Kategorie-Typ (Einnahme/Ausgabe): Vererbung, Vorzeichen-Hinweis und Erst-Bestimmung fuer bestehende Daten."""

import logging
from typing import Optional

from sqlmodel import Session, select

from app.models import (
    CATEGORY_TYPE_EXPENSE,
    CATEGORY_TYPE_INCOME,
    CATEGORY_TYPES,
    UMBUCHUNG_KEY,
    Category,
    Transaction,
    TransactionSplit,
)

# uvicorn.error: erscheint im Standard-Log der App (Add-on-Log bzw. docker logs)
logger = logging.getLogger("uvicorn.error")

TYPE_LABELS = {CATEGORY_TYPE_INCOME: "Einnahme", CATEGORY_TYPE_EXPENSE: "Ausgabe"}


def top_level_of(category: Optional[Category], by_id: dict[int, Category]) -> Optional[Category]:
    if category is None:
        return None
    if category.parent_id is None:
        return category
    return by_id.get(category.parent_id, category)


def effective_type(category: Optional[Category], by_id: dict[int, Category]) -> Optional[str]:
    """Typ einer Kategorie: bei Unterkategorien der ihrer Oberkategorie; None fuer Umbuchung/unkategorisiert."""
    top = top_level_of(category, by_id)
    if top is None or top.system_key == UMBUCHUNG_KEY:
        return None
    return top.type if top.type in CATEGORY_TYPES else None


def sign_mismatch_hint(amount: float, category_type: Optional[str]) -> Optional[str]:
    """Tooltip-Text, wenn das Vorzeichen des Betrags nicht zum Kategorie-Typ passt - sonst None.

    Nur ein Hinweis, nie eine Sperre (Rueckerstattungen, Korrekturen, Bargeld-Splits ...).
    """
    if category_type == CATEGORY_TYPE_EXPENSE and amount > 0:
        return "Ungewöhnlich: positiver Betrag in einer Ausgaben-Kategorie"
    if category_type == CATEGORY_TYPE_INCOME and amount < 0:
        return "Ungewöhnlich: negativer Betrag in einer Einnahmen-Kategorie"
    return None


def category_sign_hint(
    amount: float, category_id: Optional[int], by_id: dict[int, Category]
) -> Optional[str]:
    """sign_mismatch_hint() fuer eine zugewiesene Kategorie-ID (None ohne Kategorie)."""
    category = by_id.get(category_id) if category_id is not None else None
    if category is None:
        return None
    return sign_mismatch_hint(amount, effective_type(category, by_id))


def _detect_type(positive: int, negative: int, net: float) -> Optional[str]:
    """Typ aus den Vorzeichen der zugewiesenen Buchungen (Mehrheit nach Anzahl, bei Gleichstand nach Summe);
    None, wenn es keine Buchungen gibt."""
    if positive == negative == 0:
        return None
    if positive != negative:
        return CATEGORY_TYPE_INCOME if positive > negative else CATEGORY_TYPE_EXPENSE
    return CATEGORY_TYPE_INCOME if net > 0 else CATEGORY_TYPE_EXPENSE


def backfill_category_types(session: Session, commit: bool = True) -> dict[str, int]:
    """Setzt den Typ aller Oberkategorien, die noch keinen haben (idempotent, ueberschreibt nie).

    Mehrheit der Vorzeichen der zugewiesenen Buchungen (inkl. Unterkategorien und Bargeld-Aufteilungen),
    ohne jede Buchung "ausgabe". Die Systemkategorie "Umbuchung" bleibt ohne Typ.
    commit=False: nur flushen (Aufrufer haelt die Transaktion, z.B. der Backup-Import).
    Rueckgabe: Anzahl je Ergebnis (einnahme / ausgabe / ausgabe_ohne_buchungen).
    """
    cats = session.exec(select(Category)).all()
    by_id = {c.id: c for c in cats}
    targets = [
        c for c in cats if c.parent_id is None and c.type is None and c.system_key != UMBUCHUNG_KEY
    ]
    result = {CATEGORY_TYPE_INCOME: 0, CATEGORY_TYPE_EXPENSE: 0, "ausgabe_ohne_buchungen": 0}
    if not targets:
        return result

    stats: dict[int, list] = {c.id: [0, 0, 0.0] for c in targets}  # positiv, negativ, Summe

    def add(category_id: Optional[int], amount: float) -> None:
        top = top_level_of(by_id.get(category_id), by_id) if category_id is not None else None
        if top is None or top.id not in stats or amount == 0:
            return
        entry = stats[top.id]
        entry[0 if amount > 0 else 1] += 1
        entry[2] += amount

    for txn_category_id, amount in session.exec(
        select(Transaction.category_id, Transaction.amount).where(Transaction.category_id.is_not(None))
    ).all():
        add(txn_category_id, amount)
    for split_category_id, amount in session.exec(
        select(TransactionSplit.category_id, TransactionSplit.amount).where(
            TransactionSplit.category_id.is_not(None)
        )
    ).all():
        add(split_category_id, amount)

    for cat in targets:
        positive, negative, net = stats[cat.id]
        detected = _detect_type(positive, negative, net)
        if detected is None:
            cat.type = CATEGORY_TYPE_EXPENSE
            result["ausgabe_ohne_buchungen"] += 1
        else:
            cat.type = detected
            result[detected] += 1
        session.add(cat)
    if commit:
        session.commit()
    else:
        session.flush()
    logger.info(
        "Kategorie-Typen bestimmt: %d Einnahme, %d Ausgabe (davon %d ohne Buchungen, Fallback)",
        result[CATEGORY_TYPE_INCOME],
        result[CATEGORY_TYPE_EXPENSE] + result["ausgabe_ohne_buchungen"],
        result["ausgabe_ohne_buchungen"],
    )
    return result
