# Haushaltsbuch

Haushaltsbuch-App zur Überwachung von Ausgaben und Einnahmen über mehrere
Bankkonten hinweg. Backend: FastAPI + SQLModel (SQLite), Frontend:
Jinja2-Templates + htmx, UI-Framework [Beer CSS](https://www.beercss.com/)
(Material-Design-3-Komponenten, per CDN eingebunden) mit HA-Blau (#03a9f4)
als Primärfarbe. Läuft perspektivisch als Home-Assistant-Add-on, während der
Entwicklung eigenständig per Docker.

## Lokal starten (venv)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
DATABASE_PATH=./data/haushaltsbuch.db uvicorn app.main:app --reload --port 8000
```

App: http://localhost:8000
Health-Check: http://localhost:8000/health

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
  templates/    Jinja2-Templates
  static/       JS (htmx, Theme-Toggle); Styling kommt von Beer CSS per CDN
  database.py   DB-Engine & Session
  main.py       FastAPI-App, Health-Check, Startseite
```

## Datenbank

SQLite-Datei, Pfad über Umgebungsvariable `DATABASE_PATH` konfigurierbar
(Standard: `/data/haushaltsbuch.db`, passend für den Docker-Container).

## Hinweis: Internetzugriff im Browser

Beer CSS wird per CDN (jsDelivr) eingebunden, htmx dagegen lokal ausgeliefert.
Für die Darstellung braucht der Browser, der die App aufruft, also
Internetzugriff auf `cdn.jsdelivr.net`.
