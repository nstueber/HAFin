# Haushaltsbuch

Haushaltsbuch-App zur Überwachung von Ausgaben und Einnahmen über mehrere
Bankkonten hinweg. Backend: FastAPI + SQLModel (SQLite), Frontend:
Jinja2-Templates + htmx, Styling mit [Tailwind CSS v4](https://tailwindcss.com/)
(Standalone-CLI, kein Node.js/npm nötig) im cleanen, shadcn/Next.js-artigen
Look mit HA-Blau (#03a9f4) als Akzentfarbe. Läuft als Home-Assistant-App
(Supervisor-Add-on, siehe unten) und für die schnelle Entwicklung eigenständig per
Docker/uvicorn.

> **Repo-Struktur:** Der gesamte App-Code liegt im Unterordner `haushaltsbuch/`
> (Home-Assistant-App). Alle Pfade wie `app/...`, `Dockerfile` oder `requirements.txt` in
> diesem README beziehen sich auf `haushaltsbuch/` (also `haushaltsbuch/app/...`). Im
> Repo-Root liegen nur `repository.yaml`, `docker-compose.yml`, `.devcontainer/`,
> `.github/` und dieses README.

## Home Assistant App (Supervisor-Add-on)

- **Installation** in Home Assistant: *Einstellungen → Apps → App-Store → ⋮ → Repositories* →
  `https://github.com/nstueber/HAFin` hinzufügen. Nutzungs-/Backup-/Troubleshooting-Doku:
  [`haushaltsbuch/DOCS.md`](haushaltsbuch/DOCS.md).
- **Struktur:** `repository.yaml` (Repo-Metadaten), `haushaltsbuch/config.yaml` (App-Konfiguration:
  Ingress, `backup: cold`, `image: ghcr.io/nstueber/hafin-haushaltsbuch`), `haushaltsbuch/Dockerfile`
  (Multi-Stage: Tailwind-Build-Stage + Python-Runtime, Basis-Image direkt per `FROM`, keine
  `build.yaml`), `haushaltsbuch/run.sh` (Startskript, `exec uvicorn` als PID 1).
- **Ingress:** Hinter dem HA-Ingress liegt die App unter `/api/hassio_ingress/<token>/`; Supervisor
  entfernt das Präfix und liefert es im Header `X-Ingress-Path`. Da alle Templates/JS root-relative
  URLs nutzen, schreibt `app/ingress.py` (`IngressPathMiddleware`) sie zentral in den HTML-Antworten
  und `Location`-Headern um - nur wenn der Header vorhanden und im erwarteten Format ist, sonst
  bleibt jede Antwort unverändert (lokaler Betrieb, Docker). Neue Templates dürfen weiterhin einfach
  `/pfad` schreiben; nur *neue Top-Level-Routen* müssen in `_JS_RE` (URL-Literale in Inline-JS/JSON)
  ergänzt werden, Attribute (`href`, `src`, `action`, `hx-*`) werden unabhängig vom Pfad erfasst.
- **Schema-Migration:** Dieses Projekt nutzt bewusst **kein Alembic** - `init_db()` legt beim
  Start fehlende Tabellen/Spalten an (`_add_missing_columns`), `run.sh` braucht deshalb keinen
  separaten Migrationsschritt (Hinweis im Skript, falls Alembic später eingeführt wird).
- **Releases:** SemVer; `version` in `config.yaml`, Git-Tag `vX.Y.Z` und Eintrag in
  `haushaltsbuch/CHANGELOG.md` müssen übereinstimmen, dann `git tag vX.Y.Z && git push --tags` - der
  Workflow `.github/workflows/release.yml` baut `amd64`+`aarch64` und pusht nach GHCR (Ablauf und
  Checkliste in `haushaltsbuch/DOCS.md`). Einmalig: GHCR-Package auf *Public* stellen.
- **Lokale HA-Test-Instanz:** `.devcontainer/` (Supervisor + HA im Devcontainer, getrennt vom
  produktiven Zuhause), Anleitung in `haushaltsbuch/DOCS.md`.

## Lokal starten (venv)

```bash
cd haushaltsbuch
python3 -m venv ../.venv
source ../.venv/bin/activate
pip install -r requirements.txt
DATABASE_PATH=./data/haushaltsbuch.db uvicorn app.main:app --reload --port 8000
```

App: http://localhost:8000
Health-Check: http://localhost:8000/health

### Tailwind CSS lokal bauen

`app/static/css/app.css` wird aus `app/static/css/input.css` generiert und ist
nicht eingecheckt (siehe `.gitignore`) - vor dem ersten lokalen Start (oder
parallel zum Dev-Server im Watch-Modus) einmalig die Tailwind-Standalone-CLI
herunterladen und laufen lassen:

```bash
# einmalig herunterladen (Linux x64; für andere Plattformen siehe
# https://github.com/tailwindlabs/tailwindcss/releases/latest)
curl -sSL -o tailwindcss \
  https://github.com/tailwindlabs/tailwindcss/releases/download/v4.3.3/tailwindcss-linux-x64
chmod +x tailwindcss

# parallel zu uvicorn --reload laufen lassen, baut bei Template-Änderungen automatisch neu
./tailwindcss -i app/static/css/input.css -o app/static/css/app.css --watch
```

## Mit Docker starten

```bash
# empfohlen: Docker Compose (Volume haushaltsbuch-data, Neustart-Policy unless-stopped)
docker compose up --build

# oder manuell
docker build -t haushaltsbuch ./haushaltsbuch
docker run --rm -p 8000:8000 -v haushaltsbuch-data:/data haushaltsbuch
```

App: http://localhost:8000

## Projektstruktur

```
repository.yaml               HA-Repository-Metadaten
docker-compose.yml            schneller Dev-Loop ohne Supervisor
.devcontainer/  .vscode/      lokale HA-Test-Instanz (Supervisor + HA)
.github/workflows/release.yml Multi-Arch-Build + GHCR-Publish bei Tag vX.Y.Z
haushaltsbuch/                die Home-Assistant-App
  config.yaml Dockerfile run.sh README.md DOCS.md CHANGELOG.md icon.png logo.png
  requirements.txt
  app/
    models/       SQLModel-Datenmodelle (Konten, Kategorien, Mapping-Profile, Transaktionen)
    routers/      accounts, transactions, categories, mapping_profiles, imports (CSV-Import)
    services/     CSV-Erkennungslogik + Parsing (Encoding, Trennzeichen, Dezimaltrennzeichen, Datumsformat)
    templates/    Jinja2-Templates (inkl. _icons.html mit Heroicons-SVG-Makros)
    static/       JS (htmx, Theme-Toggle), CSS (input.css = Quelle, app.css = generiert)
    database.py   DB-Engine & Session, leichte Auto-Migration für neue Spalten
    ingress.py    HA-Ingress: URL-Umschreibung hinter dem Ingress-Pfad (Middleware)
    system_categories.py  Zugriff auf die Systemkategorien per system_key
    templating.py Zentrales Jinja2Templates-Objekt inkl. format_iban-Filter
    main.py       FastAPI-App, Health-Check, Startseite
```

## Datenbank

SQLite-Datei, Pfad über Umgebungsvariable `DATABASE_PATH` konfigurierbar
(Standard: `/data/haushaltsbuch.db`, passend für den Docker-Container).

## Mapping-Profil aus Beispiel-CSV anlegen

Beim Anlegen eines neuen Mapping-Profils wird zunächst eine Beispiel-CSV
hochgeladen. Die ersten 20 Rohzeilen werden mit Zeilennummern angezeigt, eine
wahrscheinliche Kopfzeile wird automatisch vorausgewählt (erste Zeile, deren
Feldanzahl zu mehreren Folgezeilen passt und mindestens 4 Felder hat) - das
überspringt korrekt Metadaten-Präambeln, wie sie z.B. ING-Exports vor der
eigentlichen Tabelle einfügen (Kontoinhaber, IBAN, Zeitraum, Hinweistexte).
Per Klick auf eine andere Zeile lässt sich die Kopfzeile manuell korrigieren.
Erst ab der gewählten Kopfzeile werden Zeichenkodierung (`charset-normalizer`),
Trennzeichen (`csv.Sniffer`), Dezimaltrennzeichen und Datumsformat erkannt und
vorbefüllt (weiterhin manuell änderbar), die Spalten-Zuordnung erfolgt per
Dropdown aus der erkannten Kopfzeile, mit Live-Vorschau der ersten Zeilen. Die
Anzahl der zu überspringenden Zeilen wird als `header_row_index` Teil des
gespeicherten Mapping-Profils gespeichert und beim eigentlichen CSV-Import
(siehe unten) ebenfalls angewendet. Die hochgeladene Datei liegt bis zum
Speichern des Profils unter `<DATA_DIR>/tmp_mapping_uploads/` und wird danach
gelöscht (verwaiste Uploads werden zusätzlich beim App-Start nach 6 Stunden
automatisch aufgeräumt).

## CSV-Import

Unter „Import" (eigener Navigationspunkt) werden Konto und Mapping-Profil
ausgewählt und ein Kontoauszug hochgeladen. Die CSV wird komplett mit den im
Mapping-Profil hinterlegten Einstellungen geparst (inkl. `header_row_index`
zum Überspringen einer Präambel); passen die dort erwarteten Spaltennamen
nicht zur hochgeladenen Datei, wird das mit einer klaren Fehlermeldung
abgebrochen, statt stillschweigend leere/falsche Daten zu importieren.

Jede Zeile wird einzeln behandelt:
- Buchungsdatum/Betrag lassen sich nicht parsen → Zeile wird übersprungen und
  im Ergebnis mit Zeilennummer und Fehlermeldung aufgelistet (der Rest der
  Datei wird trotzdem importiert)
- Für Konto+Buchungsdatum+Betrag+Verwendungszweck+Auftraggeber/Empfänger
  existiert bereits eine Transaktion → Zeile gilt als Duplikat und wird
  übersprungen (auch wirksam gegen doppelte Zeilen *innerhalb* derselben CSV,
  dank SQLAlchemys Autoflush werden bereits in diesem Importlauf neu
  hinzugefügte Buchungen schon vor dem Commit als Duplikat-Kandidat erkannt)
- sonst → Transaktion anlegen, Typ (Eingang/Ausgang) aus dem Vorzeichen des
  Betrags abgeleitet

Das Ergebnis zeigt Zeilen gelesen / importiert / übersprungen (Duplikat) sowie
eine Liste aller Zeilen mit Parse-Fehlern. Die Duplikat-Kachel ist klickbar und
öffnet einen (`.modal-wide`, siehe Styling-Abschnitt) Dialog mit allen
übersprungenen Zeilen (Datum, Auftraggeber/Empfänger, Verwendungszweck, Betrag,
Referenz auf die bereits vorhandene Transaktion). Umbuchungen zwischen zwei
eigenen Konten werden beim Import nicht automatisch verknüpft - das passiert
separat auf der Buchungen-Seite (siehe unten).

**Trotzdem importieren:** jede Zeile in der Duplikate-Tabelle hat eine
Checkbox; „Ausgewählte trotzdem importieren" (`POST /import/force-import`)
legt die markierten Zeilen als neue, reguläre Buchungen an und umgeht dabei
bewusst die Duplikat-Erkennung (der Nutzer bestätigt hier explizit, dass es
sich NICHT um ein Duplikat handelt). Da die urspünglichen Import-Ergebnisdaten
(Zeilen gelesen/importiert/Fehler) nur für diesen einen Request berechnet und
nicht persistiert werden, kann nach dem Force-Import nicht einfach die ganze
Seite neu geladen werden, ohne diesen Kontext zu verlieren - stattdessen
werden die urspünglichen Zeilendaten als parallele Hidden-Input-Arrays
(`all_row`/`all_date`/`all_payee`/`all_purpose`/`all_amount`) direkt im
Formular mitgeführt, und die Antwort entfernt die erfolgreich importierten
Zeilen per eingebettetem `<script>` clientseitig aus der Tabelle, statt sie
komplett neu vom Server zu laden.

## Navigation (Hauptmenü + Einstellungen-Hub)

Das Hauptmenü hat nur vier Einträge (Übersicht, Buchungen, Import, Einstellungen) - in allen drei
Varianten in `base.html` (Desktop-Sidebar, Tablet-Icon-Rail, mobile Bottom-Nav) aus denselben
`nav_item(...)`-Aufrufen. **"Einstellungen" ist ein normaler Eintrag ohne Flyout/Untermenü** und führt auf die Hub-Seite
`GET /settings` (`app/routers/settings.py`, `templates/settings/index.html`): Kacheln (Icon + Titel +
Beschreibung, mobil untereinander, ab `md` zweispaltig) zu Konten, Kategorien, Mapping-Profilen und Backup &
Restore - analog zum Einstellungen-Bereich von Home Assistant. Die Routen der Unterseiten (`/accounts`,
`/categories`, `/mapping-profiles`, `/backup`) sind unverändert.

**Aktiv-Zustand & Zurück-Link zentral in `base.html`:** die Liste `settings_children` (`active_nav`-Schlüssel
`accounts`, `categories`, `mapping_profiles`, `backup`) markiert "Einstellungen" als aktiv (`current_nav`) und blendet
über dem Inhalt automatisch den Link "← Einstellungen" ein - für jede Seite, die eines dieser `active_nav`-Werte setzt
(auch Bearbeiten-/Wizard-/Ergebnis-/Fehlerseiten). Eine neue Unterseite der Einstellungen braucht also nur den passenden
`active_nav` (und einen Eintrag in `settings_children`, falls es ein neuer Schlüssel ist) plus kachel im Hub.
Mobil (Bottom-Nav) haben vier Einträge wieder Platz für Beschriftungen (auch bei 320px ohne Abschneiden geprüft).

## Kategorien & Kategorisierung

Unter „Kategorien" (wie unter „Konten") folgt das Anlegen dem einheitlichen
Muster "Button oben rechts öffnet ein `.modal-wide`-`<dialog>`" statt eines
festen Inline-Formulars auf der Seite - Button+Formular blieben so bei
größer werdenden Formularen (Export/Import kam als eigenes Modal hinzu) ohne
wachsende Seite erreichbar. Das "Neue Kategorie"-Modal erlaubt zusätzlich
eine Mehrfachanlage: ein "+"-Icon am Zeilenende hängt eine weitere
Name+Oberkategorie-Zeile an (rein clientseitig per `<template>`-Klonen einer
unausgefüllten Vorlagenzeile, analog zum Bargeld-Aufteilen-Formular), ein
"×" entfernt eine Zeile wieder (bei der ersten Zeile per `invisible` statt
`hidden` ausgeblendet, damit die Ausrichtung der übrigen Zeilen nicht
springt). Serverseitig nimmt `POST /categories` jetzt Listen entgegen
(`name: list[str]`, `parent_id: list[str]`, FastAPI/Starlette parst mehrere
gleichnamige Formularfelder automatisch dazu) und legt alle nicht-leeren
Zeilen in einem Request an - eine einzelne Zeile ist einfach der
Sonderfall "Liste der Länge 1". Export/Import (JSON) sitzt ebenfalls in
einem eigenen Modal statt als Inline-Bereich unten auf der Seite.

Kategorien lassen sich umbenennen und umhängen (Oberkategorie ändern). Beim Löschen wird
zunächst ein Bestätigungsdialog (natives `<dialog>`, lazy per htmx-GET befüllt)
mit den konkreten Konsequenzen gezeigt:
- Hat die Kategorie Unterkategorien, werden diese beim Löschen zu
  eigenständigen Oberkategorien (nicht mitgelöscht, nicht blockiert).
- Sind der Kategorie Buchungen zugeordnet, wird deren Anzahl angezeigt - beim
  Bestätigen werden genau diese Buchungen unkategorisiert (nicht mitgelöscht).
- Die automatisch angelegten Systemkategorien "Umbuchung" und "Bargeld" sind
  weder löschbar (kein Löschen-Button, serverseitig 403) noch umbenennbar
  (Namensfeld im Bearbeiten-Formular deaktiviert mit Hinweis "Systemkategorie,
  nicht änderbar"; `POST /categories/{id}/edit` weist einen abweichenden Namen
  zusätzlich serverseitig mit 400 ab - Oberkategorie ändern bleibt möglich, in
  der Praxis hängt "Bargeld" z.B. unter einer selbst angelegten Oberkategorie).
  **Die App referenziert sie ausschließlich über `Category.system_key`
  (`"umbuchung"` / `"bargeld"`, `app/models/category.py`), nie über den
  Anzeigenamen** - Zugriff über `app/system_categories.py`
  (`get_system_category()` / `get_or_create_system_category()`). Beim App-Start
  (`categories.ensure_system_categories()`) werden beide sichergestellt, damit sie
  von Anfang an in jeder Kategorie-Auswahl auftauchen; eine bestehende Datenbank
  aus der Zeit vor dem `system_key` wird dabei einmalig migriert (die Spalte
  ergänzt `_add_missing_columns()`, danach übernimmt der Backfill die vorhandene
  Kategorie mit dem Default-Namen samt aller bereits zugeordneten Buchungen -
  keine Duplikate). In der Kategorienliste tragen sie ein kleines "System"-Badge.

**Export/Import** (JSON, `/categories/export` bzw. `/categories/import`):
Export bildet die Ober-/Unterkategorie-Hierarchie 1:1 ab
(`[{"name": "Auto", "children": ["Ladekosten", ...]}, ...]`). Import gleicht
Namen case-insensitiv gegen vorhandene Kategorien ab (Unterkategorien nur
innerhalb derselben, ebenfalls abgeglichenen Oberkategorie) - Treffer werden
übersprungen, alles andere neu angelegt; am Ende steht eine kurze
Zusammenfassung ("X importiert, Y übersprungen") über der Kategorienliste,
analog zum CSV-Import-Ergebnis.

Unter „Buchungen" zeigt die Kopfzeile „Zeige X von Y Buchungen": X ist die
Anzahl der aktuell im DOM gerenderten (und ggf. durch die Textsuche weiter
gefilterten) Zeilen, Y die tatsächliche Gesamtzahl aller Buchungen, die dem
aktiven Server-Filter (Konto-/Umbuchungs-/Unkategorisiert-Filter) entsprechen -
unabhängig von der 200-Zeilen-Begrenzung der Liste selbst, ermittelt über
eine eigene `COUNT(*)`-Abfrage (`_count_transactions()` in `transactions.py`).
X aktualisiert sich rein clientseitig live beim Tippen im Suchfeld (siehe
List.js-Abschnitt unten), Y ändert sich nur bei einem echten Filterwechsel
(neuer Seitenaufruf). Jede Zeile hat außerdem ein Kategorie-Dropdown, das die
Zuordnung per htmx sofort speichert, ohne die Seite neu zu laden.
Für noch unkategorisierte Buchungen wird zusätzlich ein Vorschlag angezeigt,
wenn auf demselben Konto bereits eine andere Buchung mit identischem Betrag
und Auftraggeber/Empfänger kategorisiert wurde - ein Klick übernimmt den
Vorschlag, er wird nie automatisch gesetzt. Bewusst *kein* automatisches
Ausblenden einer Buchung aus der aktuellen Ansicht, sobald ihr im Filter „nur
unkategorisierte anzeigen" eine Kategorie zugewiesen wird (das gab es
kurzzeitig, wurde aber auf Nutzerwunsch wieder entfernt, weil es wie ein
störendes Springen der Liste wirkte) - die Liste synchronisiert sich erst
wieder beim nächsten regulären Reload/Filterwechsel.

**"Ansicht"-Optionsmenü**: Statt für jede optionale Anzeige-Funktion einen
weiteren Button in den Tabellen-Header zu packen, sitzt ein Zahnrad-Button
("Ansicht") mit einem Dropdown-Panel (`.hafin-dropdown-panel`, generisch über
`[data-dropdown-toggle]`/`[data-dropdown-panel]` in `enhancements.js` - Klick
außerhalb oder Escape schließt es wieder) im Header. Jede Option darin ist
eine Checkbox mit `[data-toggle-class]`+`[data-toggle-target]`, die beim
Ändern eine CSS-Klasse auf dem referenzierten Element umschaltet - eine
weitere Option lässt sich also ergänzen, ohne neuen JS-Code zu schreiben,
nur eine weitere Checkbox mit den passenden `data-*`-Attributen. Optional
merkt `[data-persist-key]` den Zustand für die Dauer der Session in
`sessionStorage` (bewusst kein serverseitiges Speichern für eine reine
Anzeige-Präferenz).

Aktuell zwei Optionen:
- **Mehrfachauswahl aktivieren** (vormals ein eigener Button): blendet eine
  Checkbox-Spalte ein (rein clientseitig per CSS-Klassen-Toggle, siehe
  `.ms-cell`/`.show-ms` in `input.css` - keine serverseitige Bedingung pro
  Zeile nötig).
- **Umbuchungsspalte anzeigen**: die Spalte mit dem Umbuchungs-Status/der
  Gegenbuchung ist standardmäßig ausgeblendet (`.transfer-col`/
  `.show-transfer-col`, gleiches Muster wie `.ms-cell`/`.show-ms`) und wird
  nur bei aktiviertem Toggle eingeblendet; der Zustand wird per
  `data-persist-key="hafin-show-transfer-col"` für die Session gemerkt.

Sobald mindestens eine Buchung angehakt ist, erscheint eine
Aktionsleiste mit Kategorie-Auswahl (Tom Select) und „Kategorie zuweisen"
(`POST /transactions/bulk-category`, sammelt die angehakten Checkboxen via
`hx-include`, ohne dass ein umschließendes `<form>` nötig wäre). Bereits
verknüpfte Umbuchungen zeigen in diesem Modus gar keine Checkbox (ihre
Kategorie ist ohnehin gesperrt) und werden von einer Mehrfachzuweisung
still ignoriert, falls doch mit ausgewählt. Nach der Zuweisung leeren sich
Auswahl und Aktionsleiste automatisch (jede betroffene Zeile wird per
Out-of-Band-Swap frisch - und damit mit einer wieder unangehakten Checkbox -
neu gerendert); der Mehrfachauswahl-Modus selbst bleibt bestehen, bis er
manuell wieder über denselben Button verlassen wird.

**Bargeld-Aufteilung**: Buchungen mit der festen Kategorie "Bargeld" bekommen
in der Kategorie-Spalte einen zusätzlichen "Aufteilen"-Link (öffnet ein
`<dialog>`-Modal, `GET/POST /transactions/{id}/split-form|splits`). Dort
lassen sich beliebig viele Split-Zeilen (Betrag + Kategorie, Tom Select)
hinzufügen - neue Zeilen werden rein clientseitig per `<template>`-Klonen
eingefügt (`window.hafinInitSearchableSelects()` initialisiert das frisch
geklonte `<select data-searchable>` nachträglich, da es nicht über einen
htmx-Swap ins DOM kam). Ein Live-Rest-Betrag zeigt sofort, wie viel noch
nicht aufgeteilt ist; serverseitig wird zusätzlich geprüft, dass die Summe
der Splits den Original-Betrag nicht übersteigt (Beträge dürfen aber gerne
nicht vollständig aufgehen - der Rest bleibt "Bargeld"). Gespeichert wird
immer der komplette Zeilensatz auf einmal (bestehende Splits werden ersetzt) -
das deckt Hinzufügen, Ändern und Entfernen (Zeile vor dem Speichern einfach
per Klick auf den Trash-Button entfernen) über denselben Endpunkt ab, ganz
ohne separate Lösch-Route. Datenmodell: `TransactionSplit`
(`app/models/transaction_split.py`) mit `transaction_id`, `amount` (gleiches
Vorzeichen wie die Original-Buchung) und `category_id` - die Original-Buchung
selbst bleibt unverändert (Betrag, Kategorie "Bargeld") und bekommt nur ein
"Aufgeteilt (N)"-Badge. Für Dashboard-Summen zählt der Split-Betrag zur
jeweils zugewiesenen Kategorie und der Rest weiterhin zu "Bargeld" - macht
zusammen immer exakt den Original-Betrag, keine Doppelzählung (siehe
Dashboard-Abschnitt unten).

Die Speichern-Antwort aktualisiert zusätzlich per Out-of-Band-Swap die
Haupttabellenzeile (frisches "Aufgeteilt (N)"-Badge, ohne den Dialog zu
schließen) - das ist genau die Stelle, an der ein vermischtes Antwortformat
(Split-Formular + bare `<tr>`) einmal dazu führte, dass eine komplette
Buchungszeile inkl. Mehrfachauswahl-Checkbox lose im Modal landete, siehe die
htmx-Fragment-Parsing-Notiz weiter unten - die OOB-Zeile wird seitdem in ein
eigenes `<table><tbody>` gewickelt.

**Buchung löschen**: Mülleimer-Icon in der neuen "Aktionen"-Spalte am
Zeilenende, mit nativem `hx-confirm` vor dem eigentlichen Request (`POST
/transactions/{id}/delete`). Echtes Löschen aus der Datenbank, kein
Soft-Delete-Konzept vorhanden. Zwei Sonderfälle dabei behandelt:
- War die Buchung Teil einer bestätigten Umbuchung, bleibt die Gegenbuchung
  bestehen, verliert aber die Verknüpfung (`counter_transaction_id = None`),
  den Typ (zurück auf Eingang/Ausgang je nach Vorzeichen) und die dadurch
  feste Kategorie "Umbuchung" (`category_id = None`) - dieselbe Logik wie bei
  `unlink-transfer`, nur einseitig (die gelöschte Seite braucht keinen
  Zustand mehr).
- Hat die Buchung Bargeld-Splits, werden diese mitgelöscht (Cascade Delete,
  `TransactionSplit`-Zeilen ohne ihre Original-Buchung wären bedeutungslos).

Die Antwort besteht bewusst ausschließlich aus Out-of-Band-Elementen: die
gelöschte Zeile per `hx-swap-oob="delete"` (dieselbe Technik wie beim
Entfernen einer erledigten Umbuchungs-Vorschlagskarte, siehe unten), plus bei
Bedarf die aktualisierte Gegenbuchungszeile. Das eigentliche `hx-target` ist
ein neutraler, immer vorhandener Platzhalter-`<div>`
(`#transaction-action-result`) statt der zu löschenden Zeile selbst - analog
zum bereits bewährten Muster in `bulk_set_category()`, wo die Antwort ebenso
komplett aus Out-of-Band-Zeilen besteht und das eigentliche `hx-target` nur
ein harmloser Sammelpunkt ist. Damit bleibt die Antwort ausschließlich aus
gleichartigen `<tr>`-Elementen zusammengesetzt und tappt nicht in die unten
beschriebene htmx-Fragment-Parsing-Falle (Mischung aus rohen `<tr>` und
andersartigem OOB-Element in derselben Antwort).

**Ähnliche Zahlungen**: Auge-Icon in der "Aktionen"-Spalte öffnet ein
`.modal-wide`-Detail-Dialog (`GET /transactions/{id}/details`) mit den
Kerndaten der Buchung sowie zwei getrennten Trefferlisten (je auf die letzten
10 begrenzt, mit Hinweis bei mehr vorhandenen):
- **Exakte Treffer**: identischer Betrag UND identischer Verwendungszweck
  (ersatzweise Auftraggeber/Empfänger, falls kein Verwendungszweck gesetzt
  ist) - kontoübergreifend.
- **Ähnliche Treffer**: identischer Betrag ODER ähnlicher Verwendungszweck,
  wobei "ähnlich" bewusst simpel über `difflib.SequenceMatcher.ratio()`
  (Standardbibliothek, Schwellwert 0.6) statt einer echten
  Levenshtein-Bibliothek ermittelt wird - für eine Vorschlagsliste ohne
  automatisches Matching reicht das. Bereits als exakter Treffer gezählte
  Buchungen tauchen nicht zusätzlich hier auf.

Jede Trefferzeile ist klickbar und öffnet wiederum denselben Detail-Dialog für
die angeklickte Buchung (statt zu versuchen, die Hauptliste zu einer ggf. gar
nicht geladenen Zeile zu scrollen/filtern - robuster, da unabhängig davon, ob
die Zielbuchung gerade im 200er-Limit oder einem aktiven Suchergebnis sichtbar
ist). Beide Trefferlisten sind wie die Haupttabelle sortier-/durchsuchbar
(eigene List.js-Instanz je Liste, `sort_th()`/`table_search()` aus
`_table.html`) - da der Detail-Dialog bei jedem Öffnen komplett neu gerendert
wird (gleiche Container-IDs `similar-exact-table`/`similar-similar-table` bei
jeder neuen Buchung), greift hier dieselbe Staleness-Erkennung in
`hafinInitTable()` wie beim Dashboard-Drilldown.

**Buchung bearbeiten** (im Detail-Dialog): ein "Bearbeiten"-Button zeigt zuerst
einen nativen `confirm()`-Warnhinweis ("könnte beim nächsten Import
versehentlich doppelt importiert werden, da Datum/Betrag/Verwendungszweck/
Auftraggeber für die Duplikat-Erkennung genutzt werden") - erst nach
Bestätigung blendet reines Client-JS (`hafinConfirmEditTransaction()` in
`enhancements.js`) von der Ansicht auf ein Bearbeiten-Formular um (Datum,
Betrag, Verwendungszweck, Auftraggeber/Empfänger, Konto), beide bereits Teil
derselben Server-Antwort. "Speichern" postet an `POST /transactions/{id}/edit`
(serverseitige Validierung von Datum/Betrag/Pflichtfeldern, bei Fehler bleibt
das Formular mit den eingegebenen - nicht den alten - Werten offen), "Abbrechen"
schaltet ohne Request zurück zur Ansicht. Für Buchungen, die Teil einer
bestätigten Umbuchung sind (`counter_transaction_id` gesetzt), gibt es
weder den Bearbeiten-Button noch das Formular (nur ein Hinweistext) - ein
freies Bearbeiten könnte sonst unbemerkt die feste Betrags-/Konto-Beziehung
zur Gegenbuchung brechen; Verknüpfung erst aufheben, dann bearbeiten.

**Kommentarfeld**: freies Notizfeld pro Buchung (`Transaction.comment`,
nullable, per `_add_missing_columns()` automatisch zur bestehenden Tabelle
ergänzt), direkt im Detail-Dialog editierbar (`POST /transactions/{id}/comment`)
- bewusst UNABHÄNGIG vom Bearbeiten-Warnhinweis oben, da der Kommentar kein
Feld ist, das die Duplikat-Erkennung nutzt, und deshalb auch für Buchungen
editierbar bleibt, die Teil einer Umbuchung sind (kein Sperrhinweis nötig).

## Backup & Restore (portables JSON-Backup)

Seite "Backup & Restore" (erreichbar über Einstellungen → Kachel; `app/routers/backup.py`, Logik in `app/services/backup.py`,
Templates `templates/backup/`). Ergänzt - ersetzt nicht - das Supervisor-Backup (1:1-Snapshot des
Datenordners): ein **portables, menschenlesbares** Format für den Umzug zwischen Instanzen.

**Endpunkte** (bewusst eigenständig/skriptbar, nicht nur UI-Logik): `GET /backup/export?groups=…`
(Download, ohne `groups` alles), `POST /backup/import` (multipart: `file` *oder* `upload_id`, `mode`,
`groups`, `confirm_text`; bei `Accept: application/json` JSON-Report), `POST /backup/import/preview`
(UI: prüft die Datei, legt sie unter `DATA_DIR/tmp_backup_uploads/` ab - wie beim Mapping-Profil-Upload,
Aufräumen nach 6h beim Start/Upload), `GET /backup/safety/{name}` (Sicherheits-Backups, Dateiname per
Regex validiert). Der Export liefert zusätzlich einen `X-Backup-Report`-Header (JSON, ASCII).

**Format** (`schema_version` 1, von der App-Version unabhängig; `meta` steht zuerst): `meta`
(`format`, `schema_version`, `app_version` = Build-Arg `BUILD_VERSION` → Env `APP_VERSION`, `exported_at`,
`included_groups`, `counts`), dann `accounts`, `categories`, `mapping_profiles`, `transactions`,
`transaction_splits`, `rejected_transfer_pairs`. Jede Entität hat eine `export_id` (UUID4); alle
Verknüpfungen (`account`, `category`, `parent`, `counter_transaction`, Split→`transaction`, …) zeigen auf
diese Kennung, nie auf DB-IDs. Beim Import entstehen neue Zeilen, eine Zuordnung `export_id → Objekt` löst
die Fremdschlüssel auf (Umbuchungs-Gegenbuchungen in einem zweiten Durchlauf, weil die ID erst nach dem
Flush existiert). **Nicht** exportiert: eine Buchung→Mapping-Profil-Zuordnung (existiert im Datenmodell
nicht - Profile werden nur beim Import gewählt).

**Datengruppen** (Checkboxen bei Export UND Import): Konten, Kategorien, Mapping-Profile, Buchungen
(= Buchungen + Bargeld-Splits + abgelehnte Umbuchungs-Vorschläge; letztere gehören nicht zur Aufzählung im
Auftrag, würden aber sonst bei einem Umzug stillschweigend verloren gehen und "Keine Umbuchung"-Entscheidungen
rückgängig machen). Abhängigkeit `transactions → accounts + categories` (`REQUIRES` im Service): erzwungene
Gruppen sind angehakt+deaktiviert mit Hinweis (JS `hafinSyncGroupDeps` in `enhancements.js`), der Server
ergänzt sie zusätzlich selbst (`with_dependencies`). Enthält eine Datei Buchungen ohne Konten/Kategorien
(sehr alte Exportversion), wird nur die Buchungsgruppe mit klarem Fehlertext gesperrt.

**Systemkategorien** werden beim Import nie neu angelegt, sondern über `system_key` mit den vorhandenen
verknüpft (`_system_category()` - bewusst eine Variante OHNE Commit, siehe Transaktion); auch ihre
Oberkategorie aus dem Backup wird übernommen (in echten Daten hängt "Bargeld" unter einer Oberkategorie).
Alte Backups ohne `system_key` werden anhand des Default-Namens zugeordnet (mit Warnung).

**Toleranz**: fehlende optionale Felder (z.B. `comment` in alten Backups) bekommen Defaults, unbekannte Felder
werden ignoriert - beides als Warnung im Report. Pflichtfelder, ungültige Werte, defekte Referenzen,
doppelte `export_id`s/IBANs/Profilnamen und Kategorie-Zyklen sperren die betroffene Gruppe (mit Datensatz-
Nummer in der Meldung) **bevor** die DB angefasst wird. Beim Testen mit echten Daten aufgefallen: der
Auftraggeber/Empfänger darf leer sein (27 von 574 echten Buchungen) und wird deshalb nicht als Pflicht-Text
validiert.

**Modi**: "In leere Datenbank" (nur wenn keine Konten und keine Buchungen; serverseitig geprüft, in der UI
ausgegraut mit Begründung; vorhandene gleichnamige Kategorien mit gleicher Oberkategorie werden
wiederverwendet, gleichnamige Mapping-Profile übersprungen - jeweils mit Warnung) und "Bestehende Daten
vollständig ersetzen" (Bestätigungswort `LÖSCHEN`, in der UI live berechnete Verlustzahlen). Ersetzt wird
gruppenweise; da Buchungen nicht auf gelöschte Konten/Kategorien zeigen dürfen, löscht das Ersetzen von
Konten/Kategorien/Buchungen immer auch alle bestehenden Buchungen (`replace_plan`, Vorschau warnt explizit).
Systemkategorien bleiben mit ihren IDs bestehen. Vor dem Löschen wird ein Sicherheits-Backup des
**Gesamtbestands** nach `DATA_DIR/backups/` geschrieben (die neuesten 10 bleiben) und im Ergebnis zum
Download angeboten.

**Atomarität**: der gesamte Import (inkl. Löschen) läuft in EINER Session-Transaktion, Commit nur am Ende;
jede Ausnahme → Rollback + Meldung mit dem Schritt, bei dem es scheiterte (`ImportFailed`). Getestet mit
injiziertem Fehler im letzten Schritt (Bestand danach unverändert, inkl. rückgängig gemachtem Löschen).

**Getestet** (`~/hafin-test-data/scripts/test_backup_service.py`, `test_backup_ui.py`,
`test_backup_ingress.py`): kompletter Round-Trip mit einer Kopie der Produktions-DB (5 Konten, 61
Kategorien, 574 Buchungen, 106 Umbuchungs-Verknüpfungen, 2 Splits, 1 abgelehnter Vorschlag) → in eine frische
Instanz importiert → Bestand identisch (Felder, Verknüpfungen, Zeitstempel); Teilmengen; Ersetzen; Rollback;
Validierungs-/Toleranzfälle; UI-Abläufe inkl. Downloads; alles auch durch den simulierten Ingress.

## Suche, Negativsuche und Datumsfilter in der Buchungsliste

Die Textsuche läuft **serverseitig** über den kompletten, zum aktiven Filter
(Konto/Umbuchung/Zeitraum) passenden Datenbestand - nicht nur über die per
`LIST_LIMIT` (200) geladenen Zeilen (`GET /transactions/search-rows`, mit 300ms
Debounce über `hx-trigger="input changed delay:300ms, search"` - kein eigener
JS-Debounce-Code nötig, das übernimmt htmx nativ). Durchsucht werden
Auftraggeber/Empfänger, Verwendungszweck, Kontoname und der volle
Kategorie-Name inklusive Oberkategorie (`_category_display_name()`) - eine
Suche nach der Oberkategorie findet also auch Buchungen mit einer
zugeordneten Unterkategorie und umgekehrt. Gefundene Treffer werden bei mehr
als `SEARCH_LIMIT` (500) Treffern ebenfalls gekappt, aber deutlich großzügiger
als die normale 200er-Seitenbegrenzung. Ein Klick auf den "≠"-Button daneben
kehrt die Suche um (nur Buchungen anzeigen, die NICHT dem Suchbegriff
entsprechen) und triggert per `htmx.trigger(el, "search")` sofort eine neue
Anfrage mit dem aktuellen Suchtext.

Die "Zeige X von Y Buchungen"-Anzeige bleibt dabei korrekt getrennt: Y (Gesamt
nach Server-Filter) ändert sich nur bei einem echten Filterwechsel (Seiten-
Neuladen), X (aktuell sichtbare Treffer) wird rein clientseitig aus der
tatsächlichen Zeilenzahl im DOM abgeleitet, sowohl nach einem Server-Suche-
Swap als auch beim client-seitigen Sortieren.

**Zwei gefundene Bugs bei der Umsetzung, beide nicht offensichtlich:**
- htmx' generisches Fragment-Parsing kommt mit einer Server-Antwort, die NUR
  aus mehreren rohen `<tr>`-Elementen besteht (kein umschließendes
  `<table>`/`<tbody>`), nicht zuverlässig klar - führte zu einem
  `htmx:swapError` ("e.querySelectorAll is not a function"), obwohl die
  Antwort laut htmx-eigener Dokumentation für genau diesen Fall (Erkennung an
  den ersten Zeichen der Antwort) eigentlich automatisch in `<table><tbody>`
  gewrappt werden sollte. Behoben, indem die Server-Antwort bewusst NICHT mit
  einem zusätzlichen, anders benannten Element (z.B. einem Out-of-Band-Element
  für die Trefferzahl) vermischt wird - nur die reinen `<tr>`-Zeilen, sonst
  nichts.
- List.js' `reIndex()` (nötig, um nach einem htmx-Swap neue Zeilen zu
  erkennen) setzt intern `matchingItems` zurück, feuert dabei aber nicht
  zuverlässig das eigene `updated`-Event, auf dem die Live-Trefferzahl
  aufbaut - deshalb ruft `reindexAllTables()` in `enhancements.js` nach jedem
  `list.reIndex()` zusätzlich explizit `list.update()` auf, statt sich auf
  internes Event-Chaining zu verlassen.

**Dieselbe Bugklasse (bare `<tr>`/OOB-Element-Mischung) tauchte in einer noch
schädlicheren Form erneut auf** (Bargeld-Aufteilen-Modal, siehe unten): dort
führte die Mischung nicht zu einem harten `swapError`, sondern STILL zu
verwaistem, falsch geparstem HTML - der Browser verwirft beim Parsen eines
Fragments, das nicht mit `<tr` beginnt, die `<tr>`/`<td>`-Starttags eines
OOB-Updates am Ende der Antwort (Foster-Parenting-Regel), behält aber deren
KINDER (z.B. eine Mehrfachauswahl-Checkbox), die dann lose im Ziel-Container
landen - ohne jede Fehlermeldung. Der robuste Fix in beiden Richtungen: eine
OOB-`<tr>`, die nicht am Anfang einer Antwort steht, in ein eigenes, verstecktes
`<table><tbody>...</tbody></table>` einbetten (macht sie unabhängig vom Rest
der Antwort gültig geparstes Tabellen-Markup); wenn umgekehrt die Antwort
bereits mit einer echten `<tr>` beginnt (löst htmx' Auto-Wrap aus) und
zusätzlich ein andersartiges OOB-Element angehängt werden soll, dieses
stattdessen ebenfalls als `<tr>` rendern (der Tag eines `hx-swap-oob="delete"`-
Platzhalters ist für dessen Wirkung irrelevant, nur ID und Attribut zählen) -
so bleibt die Antwort durchgehend aus gleichartigen Elementen zusammengesetzt.

Ein Datumsbereich-Filter (Von/Bis, zwei `<input type="date">`) filtert
zusätzlich serverseitig (wirkt sich also auch auf Y aus) und ist mit den
übrigen Filtern kombinierbar - Standard ist kein Datumsfilter (alle
Zeiträume). Die Felder brauchen `!w-auto` gegen `.form-input`s eigenes
`w-full`, sonst sprengt ein einzelnes Datumsfeld als Flex-Kind die ganze
Filterzeile und der zugehörige Label-Text rutscht in die nächste Zeile.

## Umbuchungserkennung

Jede Buchung ohne Verknüpfung wird gegen alle anderen noch unverknüpften
Buchungen auf *anderen* Konten geprüft: exakt gegenteiliger Betrag,
Buchungsdatum innerhalb von ±2 Tagen. Passende Kandidaten werden an zwei
Stellen angezeigt:
- **"Umbuchungs-Vorschläge"**-Karte ganz oben auf der Buchungen-Seite: eine
  kontoübergreifende, deduplizierte Liste aller offenen Treffer (unabhängig
  von der 200-Zeilen-Begrenzung der Hauptliste darunter, damit ein Treffer
  nicht übersehen wird, nur weil eine Seite außerhalb der neuesten 200
  Buchungen liegt)
- direkt in der jeweiligen Tabellenzeile (Spalte "Umbuchung") als "Treffer"
  mit Konto/Datum/Auftraggeber

Die Vorschlagsliste dedupliziert ein erkanntes Paar A↔B unabhängig davon, von
welcher Seite die Erkennung ausgeht (ein `frozenset({a.id, b.id})` als
Dedup-Key ist dafür unabhängig von der Reihenfolge). Damit ein Paar dabei
IMMER unter derselben, vorhersagbaren `id="suggestion-{a}-{b}"` im DOM landet
(statt je nach Iterationsreihenfolge mal als "suggestion-3-7", mal als
"suggestion-7-3"), werden `a`/`b` beim Aufbau der Liste zusätzlich nach
Transaktions-ID sortiert. Das ist auch die Grundlage dafür, dass eine
Bestätigung *direkt aus der Tabellenzeile* (nicht über die Vorschläge-Karte)
die zugehörige Karte trotzdem korrekt per Out-of-Band-`hx-swap-oob="delete"`
entfernt, statt sie als scheinbar zweiten, bereits erledigten Vorschlag stehen
zu lassen.

Betrags-Matching ist immer strikt exakt (z.B. +250.00/-250.00) - sowohl für
automatische Vorschläge als auch für die manuelle Verknüpfung. Kandidaten mit
abweichendem Betrag werden nirgends angezeigt, und der Server lehnt eine
Bestätigung mit abweichenden Beträgen auch bei direktem Request ab (keine
Verknüpfung entsteht, kein Fehler wird angezeigt - der Aufruf ist einfach
wirkungslos).

Ein Klick auf "Als Umbuchung bestätigen" verknüpft beide Seiten (setzt
`counter_transaction_id` gegenseitig, den Typ auf `umbuchung` und die
Kategorie auf die feste Kategorie "Umbuchung", die bei Bedarf automatisch
angelegt wird) und aktualisiert die betroffene(n) Zeile(n) per
htmx-Out-of-Band-Swap, egal ob von der Vorschläge-Karte oder direkt aus der
Tabelle bestätigt. Es wird nie automatisch verknüpft, nur vorgeschlagen.
Solange die Verknüpfung besteht, ist die Kategorie-Auswahl für beide
Buchungen gesperrt (statt des Dropdowns erscheint ein reiner Text-Hinweis);
erst nach Aufheben der Verknüpfung wird die Kategorie wieder leer und frei
wählbar.

Ein Vorschlag lässt sich statt bestätigt auch mit "Keine Umbuchung"
verwerfen, ohne die Buchungen zu verknüpfen. Abgelehnte Paare werden
dauerhaft in der Tabelle `rejectedtransferpair` gespeichert und danach nie
wieder vorgeschlagen (weder in der Vorschläge-Karte noch als Treffer in der
Tabellenzeile) - die manuelle Verknüpfung ("Verknüpfen mit…") bleibt davon
unberührt, falls der Nutzer es sich anders überlegt.

Eine Buchung kann auch ohne bekannte Gegenbuchung manuell als Umbuchung
markiert werden (z.B. weil die CSV des Zielkontos noch nicht importiert
wurde) - sie bleibt dann unverknüpft, taucht aber weiterhin in der
Kandidatensuche auf. Wird später die passende Gegenbuchung importiert, wird
der Treffer vorgeschlagen; war die bestehende Seite bereits manuell markiert,
ist das in der Kandidatenliste mit "(markiert)" gekennzeichnet und
entsprechend priorisiert.

Zusätzlich lässt sich jede unverknüpfte Buchung auch **manuell** mit einer
bestimmten Gegenbuchung verknüpfen ("Verknüpfen mit…"): eine durchsuchbare
Tom-Select-Auswahl (dieselbe Komponente wie bei der Kategorie-Auswahl) zeigt
alle unverknüpften Buchungen anderer Konten mit exakt entgegengesetztem
Betrag, nach zeitlicher Nähe sortiert - für Fälle außerhalb des automatischen
±2-Tage-Fensters oder wenn die Auto-Erkennung aus anderen Gründen nichts
findet.

Sowohl die manuelle Markierung als auch eine bestätigte Verknüpfung (ob
automatisch vorgeschlagen oder manuell hergestellt) lassen sich wieder
aufheben (Typ fällt dann auf Eingang/Ausgang anhand des Vorzeichens zurück,
Kategorie wird geleert).

Der Filter in der Buchungsliste hat drei Zustände (kein unabhängiger
zweiter Button mehr, um widersprüchliche Kombinationen zu vermeiden):
"Alle" (Standard), "Nur Umbuchungen", "Ohne Umbuchungen" - kombinierbar mit
"nur unkategorisierte anzeigen". Die "Umbuchungs-Vorschläge"-Karte ist als
aufklappbares `<details>`-Element umgesetzt (Klick auf die Überschrift
klappt den gesamten Bereich ein/aus, kein JS nötig) und zeigt zu jeder Seite
zusätzlich den Verwendungszweck an.

**Einmalige Nachbesserung (Backfill) beim Start:** `transactions.backfill_umbuchung_categories()`
wird bei jedem App-Start aufgerufen (`main.py`) und setzt bei bereits
verknüpften Umbuchungen, die noch keine Kategorie haben (z.B. weil sie
verknüpft wurden, bevor die automatische Kategorie-Zuweisung eingeführt
wurde), nachträglich die feste Kategorie "Umbuchung" - sonst würde der Filter
"Nur unkategorisierte" solche älteren Umbuchungen fälschlich weiterhin
auflisten. Ist bereits alles korrekt gesetzt, tut der Lauf nichts (billige
Abfrage, kein spürbarer Overhead beim Start).

## Dashboard/Übersicht

Die Startseite (`/`, `app/routers/dashboard.py`) zeigt Kennzahlen und eine
Kategorie-Aufschlüsselung für einen frei wählbaren Zeitraum.

**Zeitraum:** Granularität Tag/Woche/Monat/Jahr (Standard beim Öffnen: aktueller
Monat), mit Vor-/Zurück-Navigation per Pfeil-Buttons. Intern wird der Zeitraum
über `granularity` + einen Anker-Tag `ref` (ISO-Datum) in der URL abgebildet -
`_period_bounds()` berechnet daraus Start-/Enddatum, `_shift_ref()` den Anker
für den vorherigen/nächsten Zeitraum (bei Monat/Jahr immer auf den 1. des
Ziel-Monats/-Jahres normalisiert, nicht "gleicher Tag im Vormonat", um
Edge-Cases wie den 31. zu vermeiden). Wechselt man nur die Granularität, bleibt
der bisherige Anker-Tag erhalten und der neue Zeitraum wird um diesen Tag herum
berechnet (z.B. Monat "September 2026" → Woche zeigt die Woche, die der 1.
September enthält). Derselbe 3-Zustands-Umbuchungsfilter wie in der
Buchungsansicht (Alle/Nur Umbuchungen/Ohne Umbuchungen) wirkt auf alle
Kennzahlen unten.

**Kennzahlen-Kacheln:** eine hervorgehobene Gesamt-Kachel (alle Konten) plus
eine Kachel pro Konto, jeweils Einnahmen/Ausgaben/Netto für den gewählten
Zeitraum. Diese Summen berücksichtigen ausnahmslos alle Buchungen im Zeitraum
(nicht nach Kategorie gefiltert) - nur der Umbuchungsfilter wirkt hier.
Ausgaben werden als positiver Betrag dargestellt (wie an anderer Stelle in der
App), Netto mit Vorzeichen.

**Kategorie-Aufschlüsselung:** horizontales Balkendiagramm via
[Chart.js](https://www.chartjs.org/) (CDN, `cdn.jsdelivr.net`, kein Build-Schritt),
absteigend nach Betrag sortiert. Unterkategorien werden in ihre Oberkategorie
eingerechnet (`_top_level_category_id()`), unkategorisierte Buchungen laufen in
einen eigenen Balken "Unkategorisiert" statt zu verschwinden. Angezeigt wird
der Betrag pro Oberkategorie als Absolutwert (analog zur "Ausgaben als
positiver Betrag"-Konvention der Kacheln) - eine Kategorie mit gemischten
Vorzeichen würde sonst zu einem schwer lesbaren, in beide Richtungen
ausschlagenden Balken führen. Farbpalette bewusst nicht Chart.js-Standard und
ohne Blautöne (`app/templates/index.html`, `palette`-Array) - klar
unterscheidbar vom HA-blauen Akzent, damit Balken nicht wie interaktive
Elemente wirken; "Unkategorisiert" bekommt zusätzlich eine eigene, neutrale
Graufarbe statt einer Palettenfarbe. Ein separater Konto-Filter (Tom Select,
"Alle Konten" als Standard) filtert nur dieses Diagramm, nicht die
Kennzahlen-Kacheln - technisch ein eigenes, sich per `onchange="this.form.submit()"`
selbst absendendes GET-Formular mit den übrigen Filtern als Hidden-Inputs, da
ein echtes Dropdown (statt Filter-Links wie beim Umbuchungsfilter) verlangt war.

**Klickbare Zahlen (Drilldown):** jede Einnahmen-/Ausgaben-/Netto-Zahl in den
Kennzahlen-Kacheln (Gesamt und je Konto) sowie jeder Balken der
Kategorie-Aufschlüsselung ist klickbar und öffnet ein zentriertes,
scrollbares Modal (dasselbe `<dialog>`-Muster wie die "Übersprungene
Duplikate"-Ansicht beim CSV-Import) mit den zugrunde liegenden Buchungen
(Datum, Konto, Auftraggeber/Empfänger, Verwendungszweck, Betrag) - unter
Berücksichtigung von Zeitraum, Konto- und Umbuchungsfilter sowie bei einem
Kategorie-Balken zusätzlich der jeweiligen Kategorie. Technisch:
`GET /dashboard/transactions` liefert das Modal-Inhalts-Fragment; geöffnet
wird es nicht deklarativ (`hx-get` + `hx-on::after-request`, versionsabhängige
Attribut-Syntax), sondern über eine kleine, wiederverwendbare JS-Hilfsfunktion
`hafinOpenDialog(url, dialogId, contentId)` in `enhancements.js`, die intern
`htmx.ajax(...)` nutzt und den Dialog erst nach Abschluss des Requests öffnet
- Kacheln rufen sie per `onclick` mit den vorberechneten Filter-URLs auf,
das Kategorie-Diagramm über Chart.js' eigenen `onClick`-Callback (liefert den
Index des angeklickten Balkens). Dasselbe Muster (`hafinOpenDialog`) wird auch
für die Kategorie-Löschbestätigung verwendet, siehe oben.

Das Drilldown-Modal nutzt `.modal-full` (`mx-auto w-[95vw] max-w-[1600px]`,
siehe Styling-Abschnitt - mindestens so breit wie der Hauptinhaltsbereich der
Seite, der selbst auf 1600px begrenzt ist) statt `.page-narrow`/`.modal-wide`,
da eine 5-spaltige Buchungstabelle sonst horizontal scrollen müsste, und enthält dieselbe Sortier-/Suchfunktion
wie die Haupt-Buchungsliste (List.js, `hafinInitTable(...)` mit den gleichen
sortierbaren Spaltenköpfen und Suchfeld) inkl. einer live mitlaufenden
"Zeige X von Y"-Trefferanzeige - das Fragment wird per htmx-`innerHTML`-Swap
in denselben Dialog-Container geladen, wird also bei jedem erneuten Öffnen
(mit potenziell anderen Daten) komplett neu aufgebaut; `hafinInitTable()`
prüft deshalb, ob die zuvor registrierte List.js-Instanz noch zu einem
tatsächlich im DOM vorhandenen Container gehört, bevor es eine erneute
Initialisierung überspringt - sonst würde die zweite Modal-Öffnung noch auf
der Instanz der ersten (inzwischen ersetzten) hängen bleiben.

Die Kategorie-Aufschlüsselung berücksichtigt Bargeld-Aufteilungen (siehe
oben) korrekt: eine Buchung mit Splits wird intern in mehrere Eintraege
zerlegt (Rest bei der Original-Kategorie, je ein Eintrag pro Split bei dessen
Ziel-Kategorie - `_category_entries()`), in Summe weiterhin exakt der
Original-Betrag. Ein Klick auf einen Balken, dessen Kategorie (auch) über
Splits gespeist wird, zeigt im Drilldown die betroffene Original-Buchung mit
einem "Split"-Badge und dem tatsächlichen Split-Anteil als Betrag (nicht dem
vollen Buchungsbetrag). Die Einnahmen-/Ausgaben-/Netto-Kacheln sind davon
komplett unberührt - sie summieren immer den echten, unveränderten
Buchungsbetrag, unabhängig von etwaigen Splits.

**Gestapelter Chart-Modus (Unterkategorien):** ein Umschalter über dem Chart
("Einfach" / "Gestapelt nach Unterkategorie") wechselt zwischen einem
einfachen Balken je Oberkategorie und einem gestapelten Balken, dessen
Segmente den tatsächlich zugewiesenen Unterkategorien entsprechen (native
Chart.js-Stapel-Balken, `scales.x.stacked`/`scales.y.stacked`). Beide
Datensätze (`simple_amounts` fürs einfache, `stacked_datasets` fürs gestapelte
Bild) werden serverseitig in EINEM Request vorbereitet
(`_category_chart_data()` in `dashboard.py`) und komplett im initialen
`chart_data|tojson`-Blob an die Seite übergeben - der Umschalter braucht
dadurch keinen weiteren Server-Roundtrip, er tauscht nur `chart.data.datasets`
aus und ruft `chart.update()`. Pro Oberkategorie entsteht dabei EIN Chart.js-
Dataset je tatsächlich vorkommender Unterkategorie (plus ein "Allgemein"-
Segment für direkt der Oberkategorie zugeordnete Buchungen), mit überall
0-Werten außer an der Stelle der eigenen Oberkategorie - der Standardweg für
"nicht überall gleiche Kindkategorien" bei gestapelten Chart.js-Balken.

Ein Klick auf einen **einzelnen Unterkategorie-Balken-Abschnitt** (im
gestapelten Modus) öffnet das Drilldown-Modal gefiltert auf GENAU diese
Unterkategorie (`exact=true` am Drilldown-Endpunkt) statt auf die ganze
Oberkategorie inklusive aller Geschwister-Unterkategorien - im einfachen
Modus bleibt ein Balken-Klick weiterhin ein Roll-up über die komplette
Oberkategorie samt alle ihrer Unterkategorien (unverändertes Verhalten,
`exact` fehlt/ist `false`). Beide Verhalten laufen über denselben
`_matches_category()`-Codepfad in `dashboard_transactions()`, nur mit
unterschiedlichem Vergleichsfeld (`category_id` vs. `top_category_id` je
Eintrag).

**Deutsches Zahlenformat überall:** ein zentraler Jinja-Filter
`format_currency` (`app/templating.py`, "." als Tausender-, "," als
Dezimaltrennzeichen, Euro-Zeichen, optionales `show_sign=True` für ein
führendes "+" bei positiven Werten wie beim Netto-Betrag) ersetzt alle
bisherigen `"%.2f"|format(...)`-Stellen serverseitig. Für clientseitig
gerenderte Zahlen (Chart.js-Tooltips/Achsenbeschriftungen, der live
nachgerechnete Bargeld-Aufteilen-Restbetrag) gibt es das JS-Äquivalent
`window.hafinFormatCurrency`/`window.hafinFormatNumber` in `enhancements.js`
(`Intl.NumberFormat("de-DE", ...)`) - **nicht** für `<input>`-Werte verwenden,
HTML-Zahlenfelder brauchen weiterhin "." als Dezimaltrennzeichen.

Bewusst nicht Teil dieser ersten Version: Vergleich zu Vorperioden, Trend über
mehrere Zeiträume.

## IBAN-Anzeige

IBANs werden intern kanonisch ohne Leerzeichen gespeichert, aber überall in
der UI über den zentralen Jinja2-Filter `format_iban` (`app/templating.py`)
in 4er-Gruppen formatiert angezeigt (`DE34 5001 0517 5422 1005 39`). Eingaben
beim Anlegen/Bearbeiten eines Kontos werden unabhängig von Leerzeichen
akzeptiert (z.B. beim Copy-Paste aus Bank-Portalen) und vor dem Speichern
normalisiert.

## Styling: Tailwind CSS (Standalone-CLI, ohne Node.js)

Kein npm/Node.js-Laufzeitabhängigkeit: Das `Dockerfile` lädt in einer
Build-Stage (`css-builder`) die passende
[Tailwind-Standalone-CLI](https://tailwindcss.com/blog/standalone-cli)
(Alpine/musl-Binary) herunter, kompiliert `app/static/css/input.css` gegen
alle Jinja2-Templates zu einer minifizierten, gepurgten `app.css` und kopiert
nur diese fertige Datei ins finale Image - die Build-Stage selbst (inkl.
CLI-Binary) landet nicht im Endergebnis. Konfiguration (Akzentfarbe,
Dark-Mode-Variante, wiederverwendbare Komponentenklassen wie `.btn-primary`,
`.card`, `.form-input`) steht direkt in `input.css` (Tailwind-v4-CSS-Config,
kein `tailwind.config.js` nötig). Icons sind inline SVGs aus
[Heroicons](https://github.com/tailwindlabs/heroicons) (MIT-lizenziert,
lokal in `app/templates/_icons.html` als Jinja-Makros eingebettet, kein
CDN/Font-Icon-Download zur Laufzeit nötig).

Alle statischen Assets (htmx, Tailwind-Ausgabe, Icons) werden lokal
ausgeliefert - für die reine Anzeige der App braucht der Browser keinen
Internetzugriff. Internetzugriff wird nur beim `docker build` selbst benötigt
(Tailwind-CLI-Download) sowie beim lokalen `./tailwindcss`-Download für die
Entwicklung.

Der Seiteninhalt (`<main>` in `base.html`) ist auf `max-w-[1600px]` begrenzt
statt der ursprünglichen `max-w-5xl` (1024px) - damit haben auch breite
Tabellen wie die Buchungsliste neben der Sidebar genug Platz, ohne auf sehr
breiten Monitoren komplett randlos zu wirken.

Die Desktop-Sidebar und die Tablet-Icon-Rail sind `sticky top-0` mit eigener
`h-screen`/`overflow-y-auto` - ohne das würden sie beim Scrollen einer langen
Seite (z.B. der Buchungsliste) mit dem Hauptinhalt nach oben aus dem
sichtbaren Bereich mitscrollen, da beide sonst nur gewöhnliche Kinder
desselben scrollenden Flex-Containers wären.

Formular-/Einzelkarten-Seiten (Konto/Kategorie/Mapping-Profil bearbeiten,
Import-Ergebnis) nutzen einheitlich `.page-narrow` (`mx-auto max-w-2xl`) bzw.
für inhaltsreichere Seiten wie den Mapping-Profil-Wizard `.page-wide`
(`mx-auto max-w-4xl`), zusätzlich zur `.card`-Klasse - damit sind alle diese
Seiten konsequent zentriert statt pro Seite unterschiedlich breit/linksbündig.
Listen-/Tabellenseiten nutzen weiterhin die volle Breite von `<main>` ohne
diese Klassen. Für Dialoge, die eine mehrspaltige Tabelle statt eines
einfachen Formulars zeigen ("Übersprungene Duplikate" beim CSV-Import,
Dashboard-Drilldown, Buchungsdetails/"Ähnliche Zahlungen", die neuen
"Neues Konto"/"Neue Kategorie"/"Export-Import"-Modals), gibt es zusätzlich
`.modal-wide` (`mx-auto w-[90vw] max-w-4xl`) als eigene, deutlich breitere
Klasse - eine gemeinsame Stelle statt die Breite pro Dialog einzeln zu setzen.
Dashboard-Drilldown nutzt die dritte Stufe `.modal-full` (`mx-auto w-[95vw]
max-w-[1600px]`), die mindestens so breit wie der Hauptinhaltsbereich ist
(Dialog 1368px bei 1440px Viewport, Inhalt 1120px). `.modal-wide`/`.modal-full`
sind die einzigen Stellen, die Dialogbreiten setzen. Die eigentliche
CSV-Import-Seite (`GET /import`, kein `<dialog>` sondern eine
gewöhnliche Seite) nutzte lange Zeit fälschlich `.page-narrow` statt
`.modal-wide`, obwohl sie optisch wie die anderen großen Fenster wirken
sollte - das war der eine der mehrfach gemeldeten "Fenster ist zu schmal"-
Fälle, der sich tatsächlich als echte Abweichung bestätigte (auf `.modal-wide`
umgestellt). Bei einer erneuten Meldung "Seite X ist schmäler als Seite Y":
zuerst per `grep` prüfen, welche Klasse die betroffene Seite/der Dialog
TATSÄCHLICH im aktuellen Code trägt, bevor vermutet wird, dass etwas fehlt -
mehrfach (Konto-/Kategorie-bearbeiten-Seiten) stellte sich in der
Vergangenheit heraus, dass die Klassen bereits identisch waren und die
gemeldete Seite schlicht aus dem Browser-Cache einer älteren Version kam
(harter Reload/Cache leeren behebt das dann) - es lohnt sich also, diesen
Check tatsächlich für JEDE gemeldete Seite einzeln zu machen statt pauschal
"wird schon wieder Cache sein" anzunehmen.

Natives `<dialog>` (z.B. "Übersprungene Duplikate" beim CSV-Import) wird über
`.showModal()` geöffnet. Die ursprüngliche Zentrierungslösung war eine einzige
`dialog { margin: auto; }`-Regel (gegen Tailwinds Preflight, das `margin: 0`
auf praktisch alle Elemente setzt) - das zentrierte aber nur kurze Dialoge
zuverlässig; inhaltsreichere Dialoge (Kategorie-Mehrfachanlage, Export/Import,
Buchungsdetails) klebten trotzdem oben am Viewport (`top: 0` statt zentriert),
vermutlich ein Zusammenspiel aus `position: fixed; inset: 0` (nativer
`dialog:modal`-Stil) mit einer inhaltsabhängigen `fit-content`-Höhe, das nicht
in jedem Fall zuverlässig funktioniert. Jetzt stattdessen `position: fixed;
top: 50%; left: 50%; transform: translate(-50%, -50%); margin: 0;` - eine von
der Dialoghöhe komplett unabhängige, unzweideutige Zentrierungstechnik, per
Playwright an fünf verschieden hohen Dialogen (172px bis 578px) verifiziert.

## Mobile Ansicht (unterhalb `md`, 768px)

**Root Cause für "Seite muss seitlich gescrollt werden":** die Hauptspalte in
`base.html` (`flex-1` neben der Sidebar) hatte kein `min-w-0` - ein Flex-Kind hat
standardmäßig `min-width: auto` und wächst daher auf die Breite seines breitesten
Inhalts (die Buchungstabelle: ~1000px), statt dass der `overflow-x-auto`-Wrapper
darin scrollt. Mit `min-w-0` bleibt die Seite selbst immer so breit wie der
Viewport (per Playwright für alle Seiten bei 375px geprüft: `scrollWidth ==
clientWidth`).

**Tabellen werden zu Karten** (reines CSS in `input.css`, keine zweite
Markup-Variante - die `<tr>`-Struktur mit ihren IDs bleibt, daher funktionieren
htmx-Swaps, OOB-Updates und List.js unverändert):
- `.table-stack` (generisch, mit `data-label="…"` je `<td>` für das Label per
  `::before`): Konten, Mapping-Profile, Mapping-Vorschau, "Ähnliche Zahlungen",
  Dashboard-Drilldown, Duplikate-/Fehlerliste beim Import. Zellen ohne Label
  (Titel-/Aktionszelle) laufen als normaler Block.
- `.txn-cards` (Buchungsliste): Karte mit Datum + Betrag (Zeile 1),
  Verwendungszweck (max. 2 Zeilen), Kategorie-Auswahl und Aktionen; **Konto,
  Auftraggeber und (falls aktiviert) Umbuchung** sind pro Karte über den
  "Mehr/Weniger"-Button ein-/ausklappbar (`tr.card-open`, Klick-Handler in
  `enhancements.js`; ein htmx-Swap der Zeile klappt sie wieder zu). Die
  Mehrfachauswahl-Checkbox erscheint links in der Karte.
- Die ausgeblendete Kopfzeile ersetzt ein automatisch erzeugtes Sortier-
  Auswahlfeld (`hafinAddMobileSort()` in `hafinInitTable()`, aus den
  `th.sort[data-sort]`), damit die Sortierung mobil nicht verloren geht.
- Ab `md` (Desktop/Tablet quer) bleibt alles die normale Tabelle; das
  Mapping-Profil-Formular stapelt seine Spalten-Zuordnung unterhalb `md`
  (`md:grid-cols-2`) untereinander.

**Filterleiste der Buchungsliste**: unterhalb `md` ersetzt ein "Filter"-Button
(mit Badge = Anzahl aktiver Filter: "nur unkategorisiert", Umbuchungsfilter ≠
"Alle", Datumsbereich zählt als ein Filter) neben "Ansicht" die einzelnen
Buttons; er klappt ein Panel (`#mobile-filter-panel`, gleicher generischer
Dropdown-Mechanismus wie das Ansicht-Menü) mit allen Filtern untereinander auf.
Die Desktop-Steuerelemente sind unverändert im Markup, nur per `hidden
md:inline-flex`/`md:flex` auf Mobile ausgeblendet - das Panel ist die
mobile-only Zweitdarstellung derselben (serverseitigen, per Link/Form
gesetzten) Filter.

## Sortier-/durchsuchbare Tabellen

Alle Tabellen (Konten, Mapping-Profile, Buchungen) nutzen
[List.js](https://listjs.com/) (per CDN, `cdnjs.cloudflare.com`) für
clientseitiges Sortieren per Klick auf die Spaltenüberschrift (mit
Pfeil-Indikator für die aktuelle Richtung) und ein Suchfeld, das über alle
sichtbaren Spalten filtert - kein Server-Roundtrip, da die Listen ohnehin
serverseitig begrenzt geladen werden. Wiederverwendbare Bausteine dafür:

- `app/templates/_table.html`: Jinja-Makros `table_search(...)` und
  `sort_th(label, sort_key)` für Suchfeld bzw. sortierbare Spaltenüberschrift
  mit Pfeil-Icon (Styling der Pfeil-Zustände in `input.css` unter `.sort-th`)
- `app/static/js/enhancements.js`: `hafinInitTable(containerId, valueNames, countElementId?)`
  initialisiert eine Tabelle; nach jedem htmx-Swap werden alle registrierten
  Tabellen automatisch neu indiziert (`list.reIndex()`), damit z.B. eine per
  htmx aktualisierte Buchungszeile weiterhin korrekt sortier-/durchsuchbar
  bleibt. Der optionale dritte Parameter benennt ein Element, dessen Text bei
  jedem `updated`-Event von List.js auf `list.matchingItems.length` gesetzt
  wird - Basis für die live mitlaufende "Zeige X von Y"-Trefferanzeige in der
  Buchungsliste und im Dashboard-Drilldown.

**Eigene Suchlogik statt List.js' eingebauter Suche** (Version 2.3.1 hat zwei
Bugs): List.js escaped Regex-Sonderzeichen im Suchstring, vergleicht intern
aber trotzdem nur per einfachem `indexOf()` statt per Regex - das escapte
`"\-"` taucht im echten Text nie auf, daher lieferte z.B. eine Suche nach
`"-"` nie einen Treffer. Außerdem setzte List.js' eigene keyup/input-Bindung
die Liste beim Leeren des Suchfelds nicht zuverlässig zurück (u.a. beim Klick
auf das native `<input type="search">`-Clear-Icon). Behoben, indem das
Such-`<input>` bewusst NICHT die von List.js selbst gehookte Klasse `.search`
trägt (sondern `.hafin-search-input`, rein visuell identisch, aber ohne
automatische List.js-Bindung) - `hafinInitTable()` bindet stattdessen selbst
einen einzigen `input`-Event-Listener (deckt Tippen, Backspace-bis-leer,
Markieren+Entf und den nativen Clear-Button gleichermaßen ab) und ruft
`list.search(value, customSearchFn)` mit einer eigenen, simplen
Teilstring-Suchfunktion auf, die den von List.js weiterhin vorgenommenen
Escape-Schritt rückgängig macht, bevor sie vergleicht.

Für eine neue Tabelle: `<tbody class="list" id="…">`, pro Spalte eine
`{{ sort_th(...) }}`-Kopfzeile und eine `<td>` mit passendem Value-Name als
Klasse, dazu `{{ table_search(...) }}` und ein
`hafinInitTable("…", [...])`-Aufruf - siehe `app/templates/accounts/list.html`
als einfaches Beispiel.

## Durchsuchbare Auswahlfelder (Tom Select)

[Tom Select](https://tom-select.js.org/) (per CDN, `cdn.jsdelivr.net`) macht
native `<select>`-Felder durchsuchbar, inkl. `<optgroup>`-Unterstützung für
die hierarchische Kategorie-Auswahl (Tom Select erkennt vorhandene Optgroups
im `<select>` automatisch, keine zusätzliche Konfiguration nötig). Reusable:
jedes `<select data-searchable>` wird von `app/static/js/enhancements.js`
automatisch beim Laden und nach jedem htmx-Swap initialisiert (Prüfung über
die von Tom Select selbst gesetzte `.tomselect`-Property, damit nichts doppelt
initialisiert wird). Aktuell genutzt für die Kategorie-Auswahl in der
Buchungsliste sowie die Konto-/Mapping-Profil-Auswahl beim CSV-Import; für
neue Selects reicht das Attribut `data-searchable`, kein weiterer JS-Code
nötig. Styling-Overrides für Tom Select liegen in `input.css` unter
`.ts-wrapper`/`.ts-control`/`.ts-dropdown`.

**Wichtig für den `htmx:afterSwap`-Listener in `enhancements.js`:** er wird auf
`document`, nicht auf `document.body`, registriert. `enhancements.js` wird als
normales `<script>` im `<head>` geladen und läuft synchron beim Parsen, bevor
`<body>` überhaupt existiert - ein `document.body.addEventListener(...)` an
dieser Stelle würde sofort mit `Cannot read properties of null` fehlschlagen
und der Listener würde nie registriert. Das führte real dazu, dass nach jedem
htmx-Swap (Kategorie ändern, Umbuchung bestätigen/lösen, Vorschlag
verwerfen, …) frisch eingefügte `<select data-searchable>`-Felder nie erneut
zu Tom Select konvertiert wurden - sichtbar als natives, unindiziertes
`<select>` mit doppeltem Rahmen, bis zum nächsten vollständigen Seiten-Reload.
`document` existiert dagegen von Anfang an, und htmx-Events blubbern ohnehin
bis dorthin - kein weiterer Unterschied im Verhalten, nur die Registrierung
funktioniert jetzt zuverlässig.

**Der "doppelte Rahmen" bei Tom-Select-Feldern (endgültig behoben) hatte eine
andere, rein CSS-basierte Ursache als zunächst vermutet:** Tom Select kopiert
beim Initialisieren die Klassen des ursprünglichen `<select>` (inkl. unserer
`.form-input`-Klasse und bei kompakten Selects wie der Kategorie-Auswahl
zusätzlich `!`-wichtige Utilities wie `!py-1.5`/`!text-xs`) 1:1 auf seinen
eigenen `.ts-wrapper`-Container. Dadurch bekam der Wrapper selbst schon eine
eigene sichtbare Box (Rahmen/Padding von `.form-input`), zusätzlich zu der
Box, die `.ts-wrapper .ts-control` ohnehin für das innere Control-Element
setzt - zwei verschachtelte, durch das Wrapper-Padding sichtbar getrennte
Rahmen. Das betraf technisch **alle** Tom-Select-Felder gleichermaßen
(bestätigt auch für die Konto-/Mapping-Profil-Auswahl beim Import), fiel aber
bei der kompakten Kategorie-Auswahl durch die insgesamt kleinere Boxhöhe
deutlich mehr auf. Fix: `.ts-wrapper` selbst wird mit `!important` immer auf
eine unsichtbare Box zurückgesetzt (`border-0 bg-transparent p-0
shadow-none`) - `!important` ist hier nötig, weil sonst gleich-wichtige
kopierte Utility-Klassen wie `!py-1.5` weiterhin gewinnen würden. Sichtbar ist
danach ausschließlich `.ts-control`. Diagnostiziert per Playwright/Headless-
Chromium: keine JavaScript-Fehler beim Initialisieren (die ursprüngliche
Vermutung "Gruppierung + Suche wirft einen Fehler" war falsch), sondern ein
inspizierbarer, reproduzierbarer CSS-Box-Model-Fehler (`getComputedStyle` auf
`.ts-wrapper` zeigte Rahmen+Padding, wo eigentlich nichts sein sollte).
