# Changelog

Alle nennenswerten Änderungen an dieser App werden hier festgehalten. Das Format folgt
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionierung folgt
[Semantic Versioning](https://semver.org/lang/de/).

## [Unveröffentlicht]

## [0.2.0] - 2026-09-21

### Hinzugefügt
- **Backup & Restore** (Einstellungen → Backup & Restore): portabler JSON-Export und -Import aller
  fachlichen Daten (Konten, Kategorien, Mapping-Profile, Buchungen inkl. Bargeld-Splits und abgelehnten
  Umbuchungs-Vorschlägen). Der Umfang ist bei Export und Import wählbar. Import mit Vorschau, wahlweise in eine
  leere Datenbank oder als vollständiger Ersatz (mit Bestätigungswort und automatischem Sicherheits-Backup),
  in einer einzigen Transaktion mit Rollback. Skriptbar über `GET /backup/export` und `POST /backup/import`.
  Damit lassen sich Daten auch von einer Standalone-Installation in die Home Assistant App übernehmen.
- **Einstellungen-Seite** als Hub mit Kacheln zu Konten, Kategorien, Mapping-Profilen und Backup & Restore.
- **Versionsanzeige** in der Seitenleiste und auf der Einstellungen-Seite.
- **Lizenzinformationen** (Einstellungen → Lizenzinformationen): verwendete Drittkomponenten und ihre
  Lizenzen. Im Repository liegen jetzt `LICENSE` (MIT) und `THIRD-PARTY-NOTICES.md`.

### Geändert
- **Hauptnavigation auf vier Einträge reduziert:** Übersicht, Buchungen, Import, Einstellungen. Die bisherigen
  Menüpunkte sind über die Einstellungen-Seite erreichbar, ihre Adressen bleiben gleich. Auf den Unterseiten
  führt „← Einstellungen“ zurück, und „Einstellungen“ bleibt aktiv markiert. Die mobile Navigation zeigt
  wieder alle Beschriftungen.

### Behoben
- Zu wenig Abstand zwischen dem „← Einstellungen“-Link und dem Seiteninhalt auf den Unterseiten.

### Hinweis
- Keine Änderungen am Datenbankschema. Vor dem Update empfiehlt sich trotzdem ein Backup –
  neu auch über Backup & Restore in der App.

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

[Unveröffentlicht]: https://github.com/nstueber/HAFin/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/nstueber/HAFin/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/nstueber/HAFin/releases/tag/v0.1.0
