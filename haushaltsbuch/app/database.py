import os
from pathlib import Path
from typing import Iterator

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

DATABASE_PATH = os.environ.get("DATABASE_PATH", "/data/haushaltsbuch.db")
DATA_DIR = Path(DATABASE_PATH).parent
DATA_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DATABASE_PATH}",
    connect_args={"check_same_thread": False},
)

# Additiv erhoehen (nie herabsetzen), wenn sich das DB-Schema aendert - siehe README, Abschnitt
# "Schema-Migration" fuer die verbindliche Regel (neue Spalte statt Umbenennen/Loeschen). Der Wert
# selbst steuert aktuell keine Verzweigung (es gab noch keinen Fall, der eine braucht); er ist die
# Grundlage dafuer, sobald einer noetig wird, und macht den Schema-Stand einer DB-Datei sichtbar
# (z.B. in einem Support-Fall per "SELECT value FROM app_meta").
SCHEMA_VERSION = 1


def _add_missing_columns() -> None:
    """Ergänzt fehlende Spalten in bereits bestehenden Tabellen.

    Kein Ersatz für ein echtes Migrationstool - deckt nur den Fall ab, dass dem
    Modell eine neue Spalte mit einfachem Skalar-Default hinzugefügt wurde,
    während eine ältere SQLite-Datei noch das alte Schema hat. Für komplexere
    Änderungen (Umbenennen, Typwechsel, Spalten entfernen) reicht das nicht.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # neue Tabelle wird bereits von create_all angelegt
            existing_columns = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                col_type = column.type.compile(engine.dialect)
                default_clause = ""
                if column.default is not None and column.default.is_scalar:
                    default_clause = f" DEFAULT {column.default.arg!r}"
                conn.execute(
                    text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}{default_clause}')
                )


def _ensure_schema_version() -> None:
    """Legt die Ein-Zeilen-Metadaten-Tabelle ``app_meta`` an (falls noetig) und schreibt
    ``SCHEMA_VERSION`` hinein - reine Markierung, siehe Kommentar dort."""
    with engine.begin() as conn:
        conn.execute(
            text('CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        )
        conn.execute(
            text(
                "INSERT INTO app_meta (key, value) VALUES ('schema_version', :v) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            ),
            {"v": str(SCHEMA_VERSION)},
        )


def init_db() -> None:
    # Modelle importieren, damit SQLModel.metadata sie kennt.
    import app.models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _add_missing_columns()
    _ensure_schema_version()


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
