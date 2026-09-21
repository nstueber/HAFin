#!/usr/bin/env bash
# Setzt die `version` der BEREITS INSTALLIERTEN App direkt in ihrer config.yaml - zum Testen des
# Update-Pfads in der Devcontainer-Instanz (Supervisor erkennt die App als "Update verfuegbar").
#
# Es gibt keine Kopie und keinen zweiten Slug: der Workspace ist im Devcontainer als "Lokale Apps"-
# Repository eingehaengt, die installierte App "Haushaltsbuch" (Slug local_haushaltsbuch) ist also genau
# der Ordner haushaltsbuch/ dieses Repositories. Die Datei, die hier geaendert wird, ist damit auch die
# echte config.yaml im Arbeitsverzeichnis - siehe Warnung unten.
#
# Nutzung:
#   bash .devcontainer/sync-dev-app.sh 0.2.0                 version auf 0.2.0 setzen
#   bash .devcontainer/sync-dev-app.sh 0.2.0 --local-build   dazu `image:` auskommentieren (siehe unten)
#   bash .devcontainer/sync-dev-app.sh --reset               version UND image auf den letzten Commit zuruecksetzen
#   bash .devcontainer/sync-dev-app.sh                       aktuelle Version anzeigen
#
# Danach in Home Assistant: Einstellungen -> Apps -> App-Store -> ⋮ -> Nach Updates suchen, dann
# bei "Haushaltsbuch" auf "Aktualisieren".
#
# --local-build: config.yaml enthaelt `image:`. Fuer solche Apps zieht Supervisor beim Update
# "<image>:<version>" aus der Registry - das Tag existiert erst nach dem Release. Ohne `image:` baut
# Supervisor die App stattdessen lokal aus dem Dockerfile (docker buildx), womit der aktuelle Code
# testbar ist. Die Zeile wird nicht geloescht, sondern mit der Markierung "#DEV-LOCAL-BUILD# "
# auskommentiert; --reset stellt sie wieder her. Ohne diese Option bleibt `image:` unveraendert
# (Update-ERKENNUNG testbar, das Ausfuehren scheitert bis zum Release am Pull).
#
# ACHTUNG (Release): Version und `image:` gehoeren erst beim Release in die config.yaml. Nach dem Test
# mit --reset zuruecksetzen, bevor committet wird (der Release-Workflow bricht ab, wenn die Markierung
# oder eine fehlende `image:`-Zeile committet wurde).
#
# Nur fuer die lokale Test-Instanz gedacht - NICHT gegen eine produktive HA-Instanz verwenden.
set -euo pipefail

ROOT="${WORKSPACE_DIRECTORY:-$(cd "$(dirname "$0")/.." && pwd)}"
CONFIG="$ROOT/haushaltsbuch/config.yaml"
MARKER="#DEV-LOCAL-BUILD# "

[ -f "$CONFIG" ] || { echo "config.yaml nicht gefunden: $CONFIG" >&2; exit 1; }

# gleiche Erkennung wie im Release-Workflow (version: "0.1.0" oder version: 0.1.0)
read_version() {
  sed -nE 's/^version:[[:space:]]*"?([^"[:space:]#]+)"?.*/\1/p' | head -n1
}

usage() {
  echo "Nutzung: bash .devcontainer/sync-dev-app.sh <VERSION> [--local-build] | --reset" >&2
}

CURRENT="$(read_version < "$CONFIG")"
ARG="${1:-}"
LOCAL_BUILD=0

case "$ARG" in
  "")
    echo "Aktuelle Version in $CONFIG: ${CURRENT:-?}"
    if grep -q "^${MARKER}image:" "$CONFIG"; then
      echo "image: ist auskommentiert (lokaler Baumodus aktiv)."
    fi
    usage
    exit 0
    ;;
  --reset)
    [ $# -eq 1 ] || { usage; exit 1; }
    TARGET="$(git -C "$ROOT" show HEAD:haushaltsbuch/config.yaml | read_version)"
    [ -n "$TARGET" ] || { echo "Version im letzten Commit nicht gefunden." >&2; exit 1; }
    ;;
  *)
    if ! [[ "$ARG" =~ ^[0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.-]+)?$ ]]; then
      echo "Ungueltige Version '$ARG' (erwartet z. B. 0.2.0)." >&2
      usage
      exit 1
    fi
    TARGET="$ARG"
    case "${2:-}" in
      "") ;;
      --local-build) LOCAL_BUILD=1 ;;
      *) echo "Unbekannte Option '${2}'." >&2; usage; exit 1 ;;
    esac
    [ $# -le 2 ] || { usage; exit 1; }
    ;;
esac

if [ "$(grep -c '^version:' "$CONFIG")" != "1" ]; then
  echo "Erwarte genau eine 'version:'-Zeile in $CONFIG." >&2
  exit 1
fi

sed -i -E "s/^version:.*/version: \"$TARGET\"/" "$CONFIG"

# image: - immer zuerst in den committeten Zustand bringen (auskommentierte Zeile wiederherstellen),
# bei --local-build danach neu auskommentieren; so ist der Aufruf beliebig oft wiederholbar.
sed -i "s/^${MARKER}image:/image:/" "$CONFIG"
if [ "$ARG" = "--reset" ] && ! grep -q '^image:' "$CONFIG"; then
  # Zeile fehlt komplett (z. B. von Hand geloescht): aus dem letzten Commit uebernehmen
  git -C "$ROOT" show HEAD:haushaltsbuch/config.yaml | grep '^image:' >> "$CONFIG" || true
fi
if [ "$LOCAL_BUILD" = "1" ]; then
  grep -q '^image:' "$CONFIG" || { echo "Keine 'image:'-Zeile in $CONFIG gefunden." >&2; exit 1; }
  sed -i "s/^image:/${MARKER}image:/" "$CONFIG"
fi

echo "version in $CONFIG: ${CURRENT:-?} -> $TARGET"
if [ "$ARG" = "--reset" ]; then
  echo "version und image entsprechen wieder dem letzten Commit."
else
  if [ "$LOCAL_BUILD" = "1" ]; then
    echo "image: auskommentiert -> Supervisor baut die App lokal aus dem Dockerfile."
  else
    echo "image: unveraendert -> das Update zieht ${TARGET} aus GHCR (gelingt erst nach dem Release)."
  fi
  echo "Jetzt in Home Assistant: Einstellungen -> Apps -> App-Store -> ⋮ -> Nach Updates suchen."
  echo "WARNUNG: config.yaml im Arbeitsverzeichnis ist geaendert - vor dem Commit mit '--reset' zuruecksetzen."
fi
