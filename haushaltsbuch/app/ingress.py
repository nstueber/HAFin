"""Home-Assistant-Ingress-Unterstuetzung.

Hinter dem HA-Ingress erreicht der Browser die App unter einem Pfad-Praefix
(``/api/hassio_ingress/<token>/``), das Supervisor vor dem Weiterleiten entfernt und
im Header ``X-Ingress-Path`` mitschickt. Die Templates dieser App verwenden
ausschliesslich root-relative URLs (``/accounts``, ``/static/...``, htmx-Pfade,
Redirects) - die wuerden im Ingress-Iframe auf das HA-Root statt auf die App zeigen.

Zwei sich ergaenzende Mechanismen loesen das:

1) **Serverseitig gerenderte HTML-Attribute** (``href``/``hx-get``/``hx-post``/...) schreibt
   diese Middleware zentral in der Antwort um - aber NUR, wenn der Header vorhanden ist. Ohne
   Header (lokaler Docker-/Dev-Betrieb, direkter Zugriff auf Port 8000) bleibt jede Antwort
   byte-identisch.
2) **JS-seitig gebaute Request-URLs** (bisher: ``hafinOpenDialog('/x')``) laufen NICHT durch
   diese Middleware, weil das JS diese Requests erst nach dem Ausliefern der Seite abschickt.
   Frueher gab es dafuer eine zweite Regex mit einer manuell gepflegten Liste bekannter
   Routennamen ("/transactions", "/categories", ...) - fragil, weil jede neue Route dort
   ergaenzt werden musste. Stattdessen bettet ``base.html`` den validierten Praefix als
   ``window.HB_BASE_PATH`` ein (siehe ``get_ingress_prefix()`` unten, ueber den Jinja-Global
   ``ingress_base_path`` in ``templating.py``); ``hafinOpenDialog()`` in ``enhancements.js``
   stellt ihn ueber den Helper ``hbUrl(path)`` selbst voran. Jeder neue JS-ausgeloeste Request
   MUSS durch ``hbUrl()`` laufen (siehe README, technischer Teil) statt sich auf eine gepflegte
   Routenliste zu verlassen.
"""

import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Nur das echte Supervisor-Format akzeptieren (Header wird in HTML eingebettet).
_INGRESS_PREFIX_RE = re.compile(r"^/api/hassio_ingress/[A-Za-z0-9_-]+$")

# HTML-Attribute mit root-relativer URL (href="/x", hx-post='/x', action="/" ...).
# "//host" (protokollrelativ) bleibt unangetastet.
_ATTR_RE = re.compile(
    r"""((?:href|src|action|formaction|hx-get|hx-post|hx-put|hx-patch|hx-delete|hx-push-url)"""
    r"""\s*=\s*["'])/(?!/)""",
    re.IGNORECASE,
)


def get_ingress_prefix(request: Request) -> str:
    """Validierter Ingress-Pfad-Praefix aus dem Request (ohne trailing "/"), sonst "".

    Einzige Quelle der Validierung - von der Middleware UND von ``ingress_base_path()``
    (Jinja-Global, bettet ``window.HB_BASE_PATH`` in ``base.html`` ein) verwendet, damit
    beide garantiert denselben Praefix sehen.
    """
    prefix = request.headers.get("x-ingress-path", "").rstrip("/")
    if not prefix or not _INGRESS_PREFIX_RE.match(prefix):
        return ""
    return prefix


def rewrite_html(text: str, prefix: str) -> str:
    return _ATTR_RE.sub(lambda m: f"{m.group(1)}{prefix}/", text)


class IngressPathMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        prefix = get_ingress_prefix(request)
        if not prefix:
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
