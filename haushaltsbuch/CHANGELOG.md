# Changelog

Alle nennenswerten Änderungen an dieser App werden hier festgehalten. Das Format folgt
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionierung folgt
[Semantic Versioning](https://semver.org/lang/de/).

## [Unveröffentlicht]

## [0.4.0] - 2026-09-23

### Hinzugefügt
- **Kategorie-Typ (Einnahme/Ausgabe) pro Oberkategorie.** Beim Anlegen und Bearbeiten wählbar; Unterkategorien erben den
  Typ ihrer Oberkategorie (Anzeige, nicht editierbar). Die Kategorienliste kennzeichnet ihn dezent (grün = Einnahme,
  rot = Ausgabe); „Umbuchung" bleibt neutral. Der Typ ist Teil von Backup & Restore und des Kategorien-JSON-Exports.
- **Hinweis bei ungewöhnlichem Vorzeichen:** passt das Vorzeichen einer Buchung nicht zum Typ ihrer Kategorie (z. B.
  positiver Betrag in einer Ausgaben-Kategorie), zeigt die Buchungsliste ein kleines Warn-Icon mit Tooltip – bei
  manueller Zuordnung, Massenzuweisung und Regeln (auch in der Regel-Vorschau und im CSV-Import-Ergebnis). Nur ein
  Hinweis: die Zuweisung bleibt immer möglich.

- **Beträge in den Kategorie-Diagrammen:** jeder Balken zeigt zusätzlich zur Länge den genauen Betrag; im Modus
  „Gestapelt nach Unterkategorie" den Gesamtwert der Oberkategorie am Balkenende.
- **Vorzeitraumsvergleich:** optional (im Filter-Menü der Übersicht, Standard: aus) zeigt je Kategorie die
  Veränderung gegenüber dem direkt vorherigen Zeitraum derselben Auflösung (z. B. Vormonat), inkl. Prozentwert bzw.
  „neu" ohne Vorzeitraum. Farbe nach Kategorie-Typ: bei Ausgaben ist ein Anstieg rot (schlechter), bei Einnahmen grün
  (besser). Nur im Modus „Einfach".
- Screenshots von Übersicht und Buchungsliste im README (mit erfundenen Testdaten).

### Geändert
- **Übersicht: „Kategorien im Zeitraum" getrennt nach Typ** in „Ausgaben nach Kategorie" (Rot-/Orange-Töne) und
  „Einnahmen nach Kategorie" (Grüntöne), jeweils absteigend nach Betrag. Umschalter „Einfach/Gestapelt" und
  Konto-Filter gelten für beide; ohne Werte einer Gruppe erscheint ein Platzhaltertext.
- **Filter-Menü der Übersicht zusammengelegt:** Umbuchungsfilter und Vorzeitraumsvergleich teilen sich jetzt ein
  Icon mit gemeinsamem Untermenü statt zwei getrennter Icons; der Punkt-Indikator erscheint, sobald mindestens eine
  der beiden Einstellungen vom Standard („Ohne Umbuchungen", Vergleich aus) abweicht.

### Behoben
- Beim Löschen einer aktuell unbenutzten Kategorie heißt der Bestätigungs-Button „Löschen" statt „Trotzdem löschen"
  (das „Trotzdem" ergab dort keinen Sinn). Bei tatsächlich noch verwendeten Kategorien bleibt es bei „Trotzdem
  löschen".

### Hinweis
- Beim ersten Start nach dem Update erhält jede bestehende Oberkategorie automatisch einen Typ: die Mehrheit der
  Vorzeichen ihrer Buchungen (inkl. Unterkategorien) entscheidet, ohne Buchungen gilt „Ausgabe". Die Migration ändert
  keine Buchungen und überschreibt nie einen bereits gesetzten Typ; das Ergebnis steht im App-Log. Backups aus älteren
  Versionen lassen sich weiterhin importieren (der Typ wird dabei auf dieselbe Weise bestimmt).

## [0.3.1] - 2026-09-21

### Hinzugefügt
- **Kategorisierungsregeln** (Einstellungen → Kategorisierungsregeln): Regeln aus Feld (Verwendungszweck oder
  Auftraggeber/Empfänger), Bedingung (enthält / beginnt mit / ist exakt), Vergleichswert und Ziel-Kategorie ordnen neu
  importierte Buchungen automatisch einer Kategorie zu. Die Reihenfolge ist die Priorität (Auf/Ab-Pfeile), die erste
  passende Regel gewinnt; bereits kategorisierte Buchungen bleiben unberührt. Im Detailfenster einer Buchung erstellt
  „Regel aus dieser Buchung erstellen“ eine vorausgefüllte Regel, und „Regeln jetzt anwenden“ kategorisiert
  rückwirkend bisher unkategorisierte Buchungen.
- **Budgets** (Einstellungen → Budgets): ein Monatsbetrag je Kategorie (Ober- oder Unterkategorie). Die Übersicht zeigt bei
  Zeitraum „Monat“ pro Budget einen Fortschrittsbalken (grün / gelb ab 80 % / rot über 100 %); Ausgaben einer
  Unterkategorie zählen auch ins Budget der Oberkategorie.
- **Alle Daten löschen** (Backup & Restore): kompletter Reset mit Verlust-Zusammenfassung, Bestätigungswort `LÖSCHEN` und
  automatischem Sicherheits-Backup vor dem Löschen – dieselbe Absicherung wie beim Import-Modus „ersetzen“.
- Kategorisierungsregeln und Budgets sind Teil von Backup & Restore (eigene, auswählbare Datengruppen; ältere
  Backup-Dateien ohne sie lassen sich weiterhin importieren).

- **Kategorisierungsregeln: fest zuweisen oder nur vorschlagen.** Pro Regel wählbar. Eine Vorschlags-Regel setzt die
  Kategorie nicht: die Buchung bleibt unkategorisiert (auch im Filter „nur unkategorisierte“) und die Buchungsliste zeigt
  „Vorschlag: … übernehmen“ mit Ein-Klick-Übernahme. Ein Regel-Vorschlag hat Vorrang vor dem Vorschlag anhand
  wiederkehrender Buchungen.
- **Vorschau bei „Regeln auf bestehende Buchungen anwenden“:** statt blind alle Treffer zu übernehmen, zeigt eine Liste
  Buchung, Regel und Ziel-Kategorie mit Checkbox je Treffer (standardmäßig alle angehakt). Erst „Ausgewählte anwenden“
  ändert etwas.
- **„Regel aus dieser Buchung erstellen“:** Beim Umschalten des Feld-Dropdowns (Verwendungszweck ↔ Auftraggeber/Empfänger) wird
  der Vergleichswert automatisch auf den passenden Text der Buchung gesetzt.
- **Budgets auch in der Jahresansicht** (Monatsbetrag × 12 gegen die Jahres-Ausgaben; bei Tag/Woche weiter ausgeblendet).
  Die Budget-Zeilen sind klickbar und öffnen das Drilldown mit den Buchungen der Kategorie im gewählten Zeitraum.

### Geändert
- **Übersicht:** Der Umbuchungsfilter steht beim ersten Laden auf „Ohne Umbuchungen“ (statt „Alle Buchungen“). Eine ausdrücklich
  gewählte Einstellung – auch „Alle Buchungen“ – bleibt beim Blättern und Wechseln des Zeitraums erhalten.
- **Darkmode an das Home-Assistant-Theme angelehnt:** neutrale statt bläulicher Grautöne (Hintergrund `#111111`, Karten
  `#1c1c1c`, Werte aus dem HA-Frontend); die hellen Grautöne sind ebenfalls neutral. Auch die Auswahlfelder (z. B. „Alle Konten“)
  sind im Darkmode jetzt dunkel statt weiß.
- **Backup-Import:** Es ist immer genau ein Import-Modus wählbar. Bei leerer Datenbank ist „Bestehende Daten ersetzen“
  ausgegraut und „In leere Datenbank importieren“ vorausgewählt; bei gefüllter Datenbank umgekehrt.
- **Übersicht:** Die Zeitraum-Auswahl (Tag/Woche/Monat/Jahr) ist jetzt ein zusammenhängendes Segmented-Control; der
  Umbuchungsfilter ist ein Filter-Symbol mit Dropdown (Alle Buchungen / Nur Umbuchungen / Ohne Umbuchungen) und zeigt
  einen Punkt, wenn gefiltert wird. Auch der Diagramm-Modus (Einfach/Gestapelt) nutzt das Segmented-Control.

### Behoben
- **„Neue Regel“-Dialog:** Die aufklappende Kategorie-Auswahl wurde vom Dialograhmen abgeschnitten (Scrollleiste im
  Dialog). Sie ragt jetzt über den Dialog hinaus bzw. der Dialog reserviert genug Höhe.
- **Backup-Import unter Home Assistant:** Der Bereich zum Bestätigen mit `LÖSCHEN` fehlte und „Import starten“ blieb
  wirkungslos. Ursache war dieselbe wie beim Lizenzseiten-Problem: Nach einem Update lieferte der Browser noch die alte
  `enhancements.js` aus dem Cache. Mit den versionierten Datei-URLs (siehe unten) ist das behoben.
- Nach einem App-Update konnte der Browser (hinter dem Home-Assistant-Ingress) noch das alte Stylesheet bzw. die
  alten Skripte aus dem Cache verwenden; neue Seiten wie „Lizenzinformationen“ erschienen dann unformatiert.
  Statische Dateien tragen jetzt die App-Version in der URL (`?v=…`) und werden bei jedem Aufruf per ETag
  neu validiert.

### Hinweis
- Neue Tabellen und Spalten (Kategorisierungsregeln, Budgets, Kategorie-Vorschläge) werden beim Start automatisch angelegt;
  bestehende Daten bleiben erhalten. Vor dem Update empfiehlt sich trotzdem ein Backup (Einstellungen → Backup & Restore).


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

[Unveröffentlicht]: https://github.com/nstueber/HAFin/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/nstueber/HAFin/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/nstueber/HAFin/compare/v0.2.0...v0.3.1
[0.2.0]: https://github.com/nstueber/HAFin/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/nstueber/HAFin/releases/tag/v0.1.0
