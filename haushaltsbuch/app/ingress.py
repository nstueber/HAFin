"""Home-Assistant-Ingress-Unterstuetzung.

Hinter dem HA-Ingress erreicht der Browser die App unter einem Pfad-Praefix
(``/api/hassio_ingress/<token>/``), das Supervisor vor dem Weiterleiten entfernt und
im Header ``X-Ingress-Path`` mitschickt. Die Templates und JS-Snippets dieser App
verwenden ausschliesslich root-relative URLs (``/accounts``, ``/static/...``, htmx-
Pfade, Redirects) - die wuerden im Ingress-Iframe auf das HA-Root statt auf die App
zeigen.

Statt hunderte URLs in Templates/JS anzufassen, schreibt diese Middleware die
root-relativen URLs zentral in den Antworten um - aber NUR, wenn der Header vorhanden
ist. Ohne Header (lokaler Docker-/Dev-Betrieb, direkter Zugriff auf Port 8000) bleibt
jede Antwort byte-identisch.
"""

import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Nur das echte Supervisor-Format akzeptieren (Header wird in HTML eingebettet).
_INGRESS_PREFIX_RE = re.compile(r"^/api/hassio_ingress/[A-Za-z0-9_-]+$")

# 1) HTML-Attribute mit root-relativer URL (href="/x", hx-post='/x', action="/" ...).
#    "//host" (protokollrelativ) bleibt unangetastet.
_ATTR_RE = re.compile(
    r"""((?:href|src|action|formaction|hx-get|hx-post|hx-put|hx-patch|hx-delete|hx-push-url)"""
    r"""\s*=\s*["'])/(?!/)""",
    re.IGNORECASE,
)

# 2) URL-Stringliterale in Inline-JS/JSON (hafinOpenDialog('/x'), {"url": "/x"}) - bewusst
#    auf die bekannten Top-Level-Routen dieser App beschraenkt, damit normale Texte mit
#    Anfuehrungszeichen und Schraegstrich nicht versehentlich umgeschrieben werden.
_JS_RE = re.compile(
    r"""(["'`])/((?:transactions|categories|accounts|import|mapping-profiles|categorization-rules|budgets|dashboard|backup|settings|static|health)"""
    r"""(?=[/?#"'`\s]|$))"""
)


def rewrite_html(text: str, prefix: str) -> str:
    # Reihenfolge wichtig: erst Attribute, dann Literale - das Ergebnis der ersten
    # Ersetzung ("/api/hassio_ingress/...") matcht die zweite Regex nicht erneut.
    text = _ATTR_RE.sub(lambda m: f"{m.group(1)}{prefix}/", text)
    return _JS_RE.sub(lambda m: f"{m.group(1)}{prefix}/{m.group(2)}", text)


class IngressPathMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        prefix = request.headers.get("x-ingress-path", "").rstrip("/")
        if not prefix or not _INGRESS_PREFIX_RE.match(prefix):
            return response

        location = response.headers.get("location")
        if location and location.startswith("/") and not location.startswith("//"):
            response.headers["location"] = prefix + location

        if response.headers.get("content-type", "").startswith("text/html"):
            body = b"".join([chunk async for chunk in response.body_iterator])
            headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
            return Response(
                content=rewrite_html(body.decode("utf-8"), prefix).encode("utf-8"),
                status_code=response.status_code,
                headers=headers,
            )
        return response
