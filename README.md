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
  services/     CSV-Erkennungslogik (Encoding, Trennzeichen, Dezimaltrennzeichen, Datumsformat)
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
gespeicherten Mapping-Profils und muss beim eigentlichen CSV-Import
(zukünftiger Schritt) ebenfalls angewendet werden. Die hochgeladene Datei
liegt bis zum Speichern des Profils unter `<DATA_DIR>/tmp_mapping_uploads/`
und wird danach gelöscht (verwaiste Uploads werden zusätzlich beim App-Start
nach 6 Stunden automatisch aufgeräumt).

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
