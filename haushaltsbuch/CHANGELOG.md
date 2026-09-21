# Changelog

Alle nennenswerten Änderungen an dieser App werden hier festgehalten. Das Format folgt
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionierung folgt
[Semantic Versioning](https://semver.org/lang/de/).

## [Unveröffentlicht]

### Hinzugefügt
- **Backup & Restore** (neuer Menüpunkt): portabler, menschenlesbarer JSON-Export/-Import der Konten,
  Kategorien (inkl. Systemkategorien per `system_key`), Mapping-Profile, Buchungen, Bargeld-Splits und
  abgelehnten Umbuchungs-Vorschläge. Auswählbarer Umfang bei Export und Import, Vorschau mit Kennzahlen,
  Modi „In leere Datenbank importieren“ und „Bestehende Daten vollständig ersetzen“ (mit Bestätigungswort und
  automatischem Sicherheits-Backup), Import in einer einzigen Transaktion mit Rollback, Ergebnis-Report.
  Skriptbar über `GET /backup/export` und `POST /backup/import`.

### Geändert
- Mobile Navigation: bei sieben Einträgen unter 480 px nur noch Icons (Beschriftung als Tooltip/aria-label).

## [0.1.0] - 2026-09-21

### Hinzugefügt
- Erste Veröffentlichung als Home Assistant App (Ingress, `amd64` und `aarch64`).
- Verwaltung von Konten, Kategorien (Ober-/Unterkategorien, feste Systemkategorien
  „Umbuchung“ und „Bargeld“) und Mapping-Profilen.
- CSV-Import mit automatischer Formaterkennung und Duplikat-Erkennung (inkl. nachträglichem
  Import übersprungener Zeilen).
- Buchungsliste mit serverseitiger Volltextsuche, Negativsuche, Datumsfilter, Sortierung,
  Mehrfachauswahl, Bearbeiten, Kommentar, Löschen und „Ähnliche Zahlungen“.
- Umbuchungserkennung, Bargeld-Aufteilung.
- Dashboard mit Zeitraum-Navigation, Kennzahlen, gestapeltem Kategorie-Diagramm und Drilldown.
- Mobile Ansicht (Karten statt Tabellen, Filter-Panel).
- Home-Assistant-Ingress-Unterstützung: URLs werden hinter dem Ingress-Pfad automatisch
  umgeschrieben.

### Hinweis
- Schema-Änderungen an der Datenbank werden beim Start automatisch nachgezogen; vor einem
  Update empfiehlt sich trotzdem ein Backup.

[Unveröffentlicht]: https://github.com/nstueber/HAFin/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/nstueber/HAFin/releases/tag/v0.1.0
