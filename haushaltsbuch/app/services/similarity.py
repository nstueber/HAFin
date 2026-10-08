"""Gemeinsame Text-Aehnlichkeit fuer "Aehnliche Zahlungen" (Buchungsdetails) und die Erkennung
wiederkehrender Zahlungen (app/services/recurring.py)."""

from difflib import SequenceMatcher

# Ab diesem Verhaeltnis gelten zwei Verwendungszwecke als "aehnlich" (Vorschlagsliste, kein Auto-Matching)
SIMILAR_TEXT_THRESHOLD = 0.6


def text_similarity(a: str, b: str) -> float:
    """Aehnlichkeit zweier Texte (0..1) per difflib - bewusst die Standardbibliothek statt einer echten
    Levenshtein-Bibliothek: fuer Vorschlaege/Gruppierungen reicht diese einfache, nachvollziehbare Heuristik."""
    return SequenceMatcher(None, a, b).ratio()
