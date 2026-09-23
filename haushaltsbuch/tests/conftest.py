"""Gemeinsame Fixtures fuer die Service-Unit-Tests (siehe README, Abschnitt "Unit-Tests").

Bewusst UNABHAENGIG von app.database: dessen Engine liest DATABASE_PATH (Default
"/data/haushaltsbuch.db") und legt beim Import das Verzeichnis an - fuer schnelle,
isolierte Tests reicht eine eigene In-Memory-SQLite-Engine mit demselben Schema
(SQLModel.metadata, aus app.models importiert).
"""

import pytest
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401 - registriert alle Tabellen in SQLModel.metadata


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session(engine):
    with Session(engine) as s:
        yield s
