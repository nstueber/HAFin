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

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY --from=css-builder /build/app/static/css/app.css ./app/static/css/app.css

ENV DATABASE_PATH=/data/haushaltsbuch.db
VOLUME ["/data"]

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
