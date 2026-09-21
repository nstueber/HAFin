"""Backup & Restore: portables JSON-Export/-Import (siehe app/services/backup.py).

Endpunkte (bewusst eigenstaendig und skriptbar, nicht nur UI-Logik):
- ``GET  /backup/export?groups=accounts&groups=...``  -> JSON-Datei (Download); ohne ``groups`` alles
- ``POST /backup/import``  (multipart: ``file`` ODER ``upload_id``; ``mode``; ``groups``; ``confirm_text``)
  -> Ergebnis-Report (HTML, bei ``Accept: application/json`` als JSON)
- ``POST /backup/import/preview`` (UI: Datei pruefen, Vorschau, Modus waehlen)
- ``GET  /backup/safety/{name}`` -> automatisch erzeugtes Sicherheits-Backup (Modus "ersetzen")
"""

import json
import re
import uuid
from time import time

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from sqlmodel import Session

from app.database import DATA_DIR, get_session
from app.services import backup as svc
from app.templating import templates

router = APIRouter(prefix="/backup", tags=["backup"])

BACKUP_DIR = DATA_DIR / "backups"
TMP_UPLOAD_DIR = DATA_DIR / "tmp_backup_uploads"
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
STALE_UPLOAD_MAX_AGE_SECONDS = 6 * 3600
KEEP_SAFETY_BACKUPS = 10
UPLOAD_ID_RE = re.compile(r"^[0-9a-f]{32}$")
SAFETY_NAME_RE = re.compile(r"^haushaltsbuch-sicherheitsbackup-\d{8}-\d{6}\.json$")


def cleanup_stale_uploads() -> None:
    if not TMP_UPLOAD_DIR.exists():
        return
    cutoff = time() - STALE_UPLOAD_MAX_AGE_SECONDS
    for path in TMP_UPLOAD_DIR.glob("*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


def _wants_json(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "application/json" in accept and "text/html" not in accept


def _page_context(session: Session, **extra) -> dict:
    return {
        "title": "Backup & Restore",
        "active_nav": "backup",
        "groups": svc.GROUPS,
        "group_labels": svc.GROUP_LABELS,
        "section_labels": svc.SECTION_LABELS,
        "current_counts": svc.target_counts(session),
        **extra,
    }


def _index_response(request: Request, session: Session, status_code: int = 200, **extra) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="backup/index.html",
        context=_page_context(session, **extra),
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
def backup_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    return _index_response(request, session)


@router.get("/export")
def export_backup(
    groups: list[str] = Query(default=[]), session: Session = Depends(get_session)
) -> Response:
    requested = groups or list(svc.GROUPS)
    try:
        doc, counts = svc.build_export(session, requested)
    except svc.BackupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    included = doc["meta"]["included_groups"]
    filename = svc.backup_filename()
    report = {
        "filename": filename,
        "included_groups": included,
        "excluded_groups": [g for g in svc.GROUPS if g not in included],
        "counts": counts,
    }
    return Response(
        content=svc.dump_json(doc),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # ASCII-only (HTTP-Header): die Oberflaeche zeigt daraus den Export-Report an
            "X-Backup-Report": json.dumps(report),
        },
    )


async def _read_upload(file: UploadFile) -> bytes:
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise svc.BackupError(
            f"Die Datei ist zu groß (maximal {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)."
        )
    return raw


def _tmp_path(upload_id: str):
    if not UPLOAD_ID_RE.match(upload_id or ""):
        raise svc.BackupError("Ungültige Upload-Kennung - bitte die Datei erneut auswählen.")
    return TMP_UPLOAD_DIR / f"{upload_id}.json"


def _preview_context(session: Session, parsed: svc.ParsedBackup, upload_id: str) -> dict:
    counts = svc.target_counts(session)
    statuses = {g: parsed.status(g) for g in svc.GROUPS}
    problems = [msg for group in svc.GROUPS for msg in parsed.problems.get(group, [])]
    return {
        "upload_id": upload_id,
        "parsed": parsed,
        "meta": parsed.meta,
        "section_counts": parsed.counts(),
        "statuses": statuses,
        "importable": [g for g in svc.GROUPS if statuses[g][0]],
        "problems": problems,
        "warnings": parsed.warnings,
        "target_counts": counts,
        "target_empty": svc.target_is_empty(counts),
        "confirm_word": svc.CONFIRM_WORD,
        "requires": svc.REQUIRES,
    }


@router.post("/import/preview", response_class=HTMLResponse)
async def import_preview(
    request: Request, file: UploadFile = File(...), session: Session = Depends(get_session)
) -> HTMLResponse:
    try:
        raw = await _read_upload(file)
        parsed = svc.parse_backup(raw)
    except svc.BackupError as exc:
        return _index_response(request, session, status_code=400, import_error=str(exc))
    TMP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    cleanup_stale_uploads()
    upload_id = uuid.uuid4().hex
    (TMP_UPLOAD_DIR / f"{upload_id}.json").write_bytes(raw)
    return templates.TemplateResponse(
        request=request,
        name="backup/preview.html",
        context=_page_context(session, **_preview_context(session, parsed, upload_id)),
    )


def _write_safety_backup(session: Session) -> str:
    """Aktuellen Gesamtbestand VOR dem destruktiven Schritt als JSON sichern."""
    doc, _ = svc.build_export(session, svc.GROUPS)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    name = svc.backup_filename("haushaltsbuch-sicherheitsbackup")
    (BACKUP_DIR / name).write_bytes(svc.dump_json(doc))
    # nur die neuesten Sicherheits-Backups behalten
    old = sorted(BACKUP_DIR.glob("haushaltsbuch-sicherheitsbackup-*.json"))[:-KEEP_SAFETY_BACKUPS]
    for path in old:
        try:
            path.unlink()
        except OSError:
            pass
    return name


@router.get("/safety/{name}")
def download_safety_backup(name: str) -> Response:
    if not SAFETY_NAME_RE.match(name):
        return Response(status_code=404)
    path = BACKUP_DIR / name
    if not path.is_file():
        return Response(status_code=404)
    return FileResponse(path, media_type="application/json", filename=name)


@router.post("/import")
async def run_import(
    request: Request,
    mode: str = Form(...),
    upload_id: str = Form(""),
    file: UploadFile | None = File(default=None),
    groups: list[str] = Form(default=[]),
    confirm_text: str = Form(""),
    session: Session = Depends(get_session),
):
    wants_json = _wants_json(request)
    safety_name = None

    def fail(message: str, status_code: int = 400):
        if wants_json:
            return JSONResponse({"error": message, "safety_backup": safety_name}, status_code=status_code)
        return templates.TemplateResponse(
            request=request,
            name="backup/result.html",
            context=_page_context(session, error=message, safety_backup=safety_name, report=None),
            status_code=status_code,
        )

    try:
        if file is not None and file.filename:
            raw = await _read_upload(file)
        else:
            path = _tmp_path(upload_id)
            if not path.is_file():
                raise svc.BackupError(
                    "Die hochgeladene Datei ist nicht mehr vorhanden (abgelaufen) - bitte erneut auswählen."
                )
            raw = path.read_bytes()
        parsed = svc.parse_backup(raw)

        if mode not in ("empty", "replace"):
            raise svc.BackupError("Unbekannter Import-Modus.")
        # Ohne explizite Auswahl (Skript-Aufruf): alles importieren, was die Datei hergibt
        requested = groups or [g for g in svc.GROUPS if parsed.status(g)[0]]
        selected = svc.resolve_selection(parsed, requested)

        counts = svc.target_counts(session)
        if mode == "empty":
            if not svc.target_is_empty(counts):
                raise svc.BackupError(
                    "Der Modus „In leere Datenbank importieren“ ist nicht möglich: die Zieldatenbank "
                    f"enthält bereits {counts['accounts']} Konto/Konten und {counts['transactions']} Buchung(en)."
                )
        else:
            if confirm_text.strip().upper() != svc.CONFIRM_WORD:
                raise svc.BackupError(
                    f"Bestätigung fehlt: zum Ersetzen der bestehenden Daten muss das Wort „{svc.CONFIRM_WORD}“ "
                    "eingegeben werden."
                )
            safety_name = _write_safety_backup(session)

        report = svc.execute_import(session, parsed, selected, mode)
        report.safety_backup = safety_name
    except svc.BackupError as exc:
        return fail(str(exc))

    if upload_id and UPLOAD_ID_RE.match(upload_id):
        try:
            (TMP_UPLOAD_DIR / f"{upload_id}.json").unlink(missing_ok=True)
        except OSError:
            pass
    if wants_json:
        return JSONResponse(report.to_dict())
    return templates.TemplateResponse(
        request=request,
        name="backup/result.html",
        context=_page_context(
            session,
            report=report,
            error=None,
            safety_backup=safety_name,
        ),
    )
