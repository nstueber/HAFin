"""App-Version: einzige Quelle ist das Feld ``version`` in ``config.yaml``.

``config.yaml`` liegt neben dem ``app``-Paket (im Repo ``haushaltsbuch/config.yaml``, im Image
``/app/config.yaml``) und wird zur Laufzeit gelesen - so aktualisiert sich die Anzeige bei jedem
Release mit dem Versions-Bump, ohne dass die Nummer an weiteren Stellen gepflegt wird.
Ohne lesbare Datei greift die Umgebungsvariable ``APP_VERSION`` (im Image aus BUILD_VERSION), sonst "dev".
"""

import os
import re
from functools import lru_cache
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

# gleiche Erkennung wie im Release-Workflow: version: "0.1.0" / version: 0.1.0 (+ optionaler Kommentar)
_VERSION_RE = re.compile(r"""^version:\s*["']?([^"'\s#]+)["']?""", re.MULTILINE)


@lru_cache(maxsize=1)
def get_app_version() -> str:
    try:
        match = _VERSION_RE.search(CONFIG_PATH.read_text(encoding="utf-8"))
    except OSError:
        match = None
    if match:
        return match.group(1)
    return os.environ.get("APP_VERSION") or "dev"
