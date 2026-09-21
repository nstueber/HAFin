# Multi-Stage-Build: Tailwind-CLI/Build-Stage ist verwerfbar, das finale Image enthaelt
# nur Python-Runtime + kompiliertes CSS + Anwendungscode (kein Node/Tailwind zur Laufzeit).
# Kein build.yaml: das Basis-Image steht direkt im FROM (Stand der HA-App-Doku).

# --- Stage 1: Tailwind CSS kompilieren (Standalone-CLI, kein Node.js nötig) ---
FROM alpine:3.20 AS css-builder
ARG TARGETARCH

RUN apk add --no-cache curl libstdc++ libgcc

WORKDIR /build
RUN case "$TARGETARCH" in \
      amd64) TW_ARCH=x64 ;; \
      arm64) TW_ARCH=arm64 ;; \
      *) echo "Nicht unterstützte Architektur: $TARGETARCH" >&2; exit 1 ;; \
    esac && \
    curl -sSL -o tailwindcss \
      "https://github.com/tailwindlabs/tailwindcss/releases/download/v4.3.3/tailwindcss-linux-${TW_ARCH}-musl" && \
    chmod +x tailwindcss

COPY app/templates ./app/templates
COPY app/static/css/input.css ./app/static/css/input.css

RUN ./tailwindcss -i ./app/static/css/input.css -o ./app/static/css/app.css --minify --cwd .

# --- Stage 2: Anwendungsimage ---
FROM python:3.12-alpine

# Vom home-assistant/builder als Build-Args gesetzt (Default fuer lokale Builds)
ARG BUILD_ARCH=local
ARG BUILD_VERSION=dev

LABEL \
  io.hass.type="addon" \
  io.hass.arch="${BUILD_ARCH}" \
  io.hass.version="${BUILD_VERSION}" \
  org.opencontainers.image.title="Haushaltsbuch" \
  org.opencontainers.image.source="https://github.com/nstueber/HAFin" \
  org.opencontainers.image.version="${BUILD_VERSION}"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
# Versionsquelle: app/version.py liest "version" zur Laufzeit aus /app/config.yaml
COPY config.yaml ./config.yaml
# Lizenzseite der App (Einstellungen -> Lizenzinformationen)
COPY THIRD-PARTY-NOTICES.md ./THIRD-PARTY-NOTICES.md
COPY --from=css-builder /build/app/static/css/app.css ./app/static/css/app.css
COPY run.sh /run.sh
RUN chmod +x /run.sh

# /data ist in Home Assistant das persistente App-Verzeichnis (Docker-Volume)
ENV DATABASE_PATH=/data/haushaltsbuch.db
# Fallback fuer die angezeigte Version (meta.app_version, Oberflaeche), falls config.yaml fehlt
ENV APP_VERSION=${BUILD_VERSION}
VOLUME ["/data"]

EXPOSE 8000

CMD ["/run.sh"]
