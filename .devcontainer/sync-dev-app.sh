#!/usr/bin/env bash
# Legt im Devcontainer eine LOKAL BAUBARE Kopie der App im "Lokale Apps"-Repository an.
#
# Warum: haushaltsbuch/config.yaml enthaelt `image: ghcr.io/...` (fuer Release-Installationen).
# Bei Apps mit `image` versucht Supervisor, dieses Image zu ziehen statt lokal zu bauen - vor dem
# ersten Release (oder fuer ungetaggte Aenderungen) existiert es aber nicht. Die Kopie hat kein
# `image`, einen eigenen Slug/Namen und wird von Supervisor aus dem Dockerfile gebaut.
#
# Nutzung:  bash .devcontainer/sync-dev-app.sh [VERSION]
#   VERSION (optional) ueberschreibt `version` der Kopie - zum Testen des Update-Pfads
#   (z. B. erst mit 0.1.0 installieren, dann `sync-dev-app.sh 0.1.1` und im Store aktualisieren).
#
# Nur fuer die lokale Test-Instanz gedacht - NICHT gegen eine produktive HA-Instanz verwenden.
set -euo pipefail

SRC="${WORKSPACE_DIRECTORY:-$(cd "$(dirname "$0")/.." && pwd)}/haushaltsbuch"
DEST="${DEV_APP_DEST:-/mnt/supervisor/apps/local/haushaltsbuch-dev}"
VERSION="${1:-}"

[ -f "$SRC/config.yaml" ] || { echo "config.yaml nicht gefunden in $SRC" >&2; exit 1; }

rm -rf "$DEST"
mkdir -p "$DEST"
# Build-Artefakte/Caches nicht mitkopieren (app.css wird im Docker-Build neu erzeugt)
tar -C "$SRC" --exclude='__pycache__' --exclude='app/static/css/app.css' -cf - . | tar -C "$DEST" -xf -

sed -i \
  -e '/^image:/d' \
  -e 's/^slug: .*/slug: "haushaltsbuch_dev"/' \
  -e 's/^name: .*/name: "Haushaltsbuch (Dev)"/' \
  "$DEST/config.yaml"
if [ -n "$VERSION" ]; then
  sed -i -e "s/^version: .*/version: \"$VERSION\"/" "$DEST/config.yaml"
fi

echo "Dev-Kopie angelegt: $DEST"
grep -E '^(name|version|slug|image):' "$DEST/config.yaml" || true
echo "Jetzt in Home Assistant: Einstellungen -> Apps -> App-Store -> ⋮ -> Nach Updates suchen."
