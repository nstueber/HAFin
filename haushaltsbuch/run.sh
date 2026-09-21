#!/bin/sh
# Startskript der Home-Assistant-App (und des lokalen Docker-Images).
#
# Schema-Migration: Dieses Projekt nutzt KEIN Alembic. Beim Start des Servers
# (FastAPI-Startup-Hook -> app.database.init_db()) werden fehlende Tabellen angelegt
# und fehlende Spalten ergaenzt (_add_missing_columns), bevor die erste Anfrage bedient
# wird - ein separater Migrationsschritt vor dem Serverstart ist daher nicht noetig.
# Falls spaeter Alembic eingefuehrt wird, hier VOR dem uvicorn-Aufruf
# "alembic upgrade head" ergaenzen.
set -e

PORT="${INGRESS_PORT:-8000}"   # muss zu ingress_port in config.yaml passen

# exec: uvicorn wird PID 1 und bekommt SIGTERM direkt (init: false in config.yaml,
# es gibt keinen Init-Prozess dazwischen) - sauberes Herunterfahren beim Stoppen/Backup.
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
