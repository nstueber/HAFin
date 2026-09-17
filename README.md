# Haushaltsbuch

Haushaltsbuch-App zur Überwachung von Ausgaben und Einnahmen über mehrere
Bankkonten hinweg. Backend: FastAPI + SQLModel (SQLite), Frontend:
Jinja2-Templates + htmx, Styling mit [Tailwind CSS v4](https://tailwindcss.com/)
(Standalone-CLI, kein Node.js/npm nötig) im cleanen, shadcn/Next.js-artigen
Look mit HA-Blau (#03a9f4) als Akzentfarbe. Läuft perspektivisch als
Home-Assistant-Add-on, während der Entwicklung eigenständig per Docker.

## Lokal starten (venv)

```bash
python3 -m venv .venv
source .venv/bin/activate
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
docker build -t haushaltsbuch .
docker run --rm -p 8000:8000 -v haushaltsbuch-data:/data haushaltsbuch
```

App: http://localhost:8000

## Projektstruktur

```
app/
  models/       SQLModel-Datenmodelle (Konten, Kategorien, Mapping-Profile, Transaktionen)
  routers/      accounts, transactions, categories, mapping_profiles, imports (CSV-Import)
  services/     CSV-Erkennungslogik + Parsing (Encoding, Trennzeichen, Dezimaltrennzeichen, Datumsformat)
  templates/    Jinja2-Templates (inkl. _icons.html mit Heroicons-SVG-Makros)
  static/       JS (htmx, Theme-Toggle), CSS (input.css = Quelle, app.css = generiert)
  database.py   DB-Engine & Session, leichte Auto-Migration für neue Spalten
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
öffnet ein Dialog mit allen übersprungenen Zeilen (Datum, Auftraggeber/
Empfänger, Verwendungszweck, Betrag, Referenz auf die bereits vorhandene
Transaktion). Umbuchungen zwischen zwei eigenen Konten werden beim Import
nicht automatisch verknüpft - das passiert separat auf der Buchungen-Seite
(siehe unten).

## Kategorien & Kategorisierung

Unter „Kategorien" lassen sich zweistufige Ober-/Unterkategorien anlegen,
umbenennen, umhängen (Oberkategorie ändern) und löschen (blockiert, solange
noch Unterkategorien oder zugeordnete Buchungen daran hängen).

Unter „Buchungen" werden die neuesten 200 importierten Transaktionen gelistet
(mit Filter „nur unkategorisierte anzeigen"). Jede Zeile hat ein
Kategorie-Dropdown, das die Zuordnung per htmx sofort speichert, ohne die
Seite neu zu laden. Für noch unkategorisierte Buchungen wird zusätzlich ein
Vorschlag angezeigt, wenn auf demselben Konto bereits eine andere Buchung mit
identischem Betrag und Auftraggeber/Empfänger kategorisiert wurde - ein Klick
übernimmt den Vorschlag, er wird nie automatisch gesetzt.

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

Formular-/Einzelkarten-Seiten (Konto/Kategorie/Mapping-Profil bearbeiten,
CSV-Import, Import-Ergebnis) nutzen einheitlich `.page-narrow`
(`mx-auto max-w-2xl`) bzw. für inhaltsreichere Seiten wie den
Mapping-Profil-Wizard `.page-wide` (`mx-auto max-w-4xl`), zusätzlich zur
`.card`-Klasse - damit sind alle diese Seiten konsequent zentriert statt
pro Seite unterschiedlich breit/linksbündig. Listen-/Tabellenseiten nutzen
weiterhin die volle Breite von `<main>` ohne diese Klassen.

Natives `<dialog>` (z.B. "Übersprungene Duplikate" beim CSV-Import) wird
über `.showModal()` geöffnet; Tailwinds Preflight setzt `margin: 0` auf
praktisch alle Elemente und hebt damit die native `margin: auto`-Zentrierung
von `<dialog>` auf - dagegen steht in `input.css` eine explizite
`dialog { margin: auto; }`-Regel.

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
- `app/static/js/enhancements.js`: `hafinInitTable(containerId, valueNames)`
  initialisiert eine Tabelle; nach jedem htmx-Swap werden alle registrierten
  Tabellen automatisch neu indiziert (`list.reIndex()`), damit z.B. eine per
  htmx aktualisierte Buchungszeile weiterhin korrekt sortier-/durchsuchbar
  bleibt

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
