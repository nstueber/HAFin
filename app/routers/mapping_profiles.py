import re
import uuid
from pathlib import Path
from time import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.database import DATA_DIR, get_session
from app.models import MappingProfile
from app.services.csv_detection import (
    RAW_PREVIEW_LINE_LIMIT,
    analyze,
    build_preview_rows,
    decode_lines,
    reparse_for_preview,
)
from app.templating import templates

router = APIRouter(prefix="/mapping-profiles", tags=["mapping-profiles"])

TMP_UPLOAD_DIR = DATA_DIR / "tmp_mapping_uploads"
STALE_UPLOAD_MAX_AGE_SECONDS = 6 * 3600
UPLOAD_ID_RE = re.compile(r"^[0-9a-f]{32}$")

MAPPING_FIELDS = ("date_column", "payee_column", "purpose_column", "amount_column")
MAPPING_LABELS = {
    "date_column": "Buchungsdatum",
    "payee_column": "Auftraggeber/Empfänger",
    "purpose_column": "Verwendungszweck",
    "amount_column": "Betrag",
}


def cleanup_stale_uploads() -> None:
    if not TMP_UPLOAD_DIR.exists():
        return
    cutoff = time() - STALE_UPLOAD_MAX_AGE_SECONDS
    for path in TMP_UPLOAD_DIR.glob("*.csv"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


def _upload_path(upload_id: str) -> Path:
    if not UPLOAD_ID_RE.match(upload_id):
        raise HTTPException(status_code=400, detail="Ungültige Upload-ID.")
    return TMP_UPLOAD_DIR / f"{upload_id}.csv"


def _clean_mapping(raw_mapping: dict) -> dict:
    return {key: (value or None) for key, value in raw_mapping.items()}


def _step2_context(
    *,
    upload_id: str,
    name: str,
    encoding: str,
    delimiter: str,
    decimal_separator: str,
    date_format: str,
    header_row_index: int,
    raw_preview_lines: list,
    header: list,
    mapping: dict,
    preview_rows: list,
    parse_error: str | None,
    form_error: str | None = None,
) -> dict:
    return {
        "title": "Neues Mapping-Profil",
        "active_nav": "mapping_profiles",
        "upload_id": upload_id,
        "name": name,
        "encoding": encoding,
        "delimiter": delimiter,
        "decimal_separator": decimal_separator,
        "date_format": date_format,
        "header_row_index": header_row_index,
        "raw_preview_lines": raw_preview_lines,
        "header": header,
        "mapping": mapping,
        "preview_rows": preview_rows,
        "parse_error": parse_error,
        "form_error": form_error,
        "mapping_fields": MAPPING_FIELDS,
        "mapping_labels": MAPPING_LABELS,
    }


def _form_to_fields(
    name: str,
    delimiter: str,
    decimal_separator: str,
    encoding: str,
    date_format: str,
    header_row_index: int,
    date_column: str,
    payee_column: str,
    purpose_column: str,
    amount_column: str,
) -> dict:
    return {
        "name": name.strip(),
        "delimiter": delimiter,
        "decimal_separator": decimal_separator,
        "encoding": encoding.strip(),
        "date_format": date_format.strip(),
        "header_row_index": max(0, header_row_index),
        "date_column": date_column.strip(),
        "payee_column": payee_column.strip(),
        "purpose_column": purpose_column.strip(),
        "amount_column": amount_column.strip(),
    }


@router.get("", response_class=HTMLResponse)
def list_profiles(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    profiles = session.exec(select(MappingProfile).order_by(MappingProfile.name)).all()
    return templates.TemplateResponse(
        request=request,
        name="mapping_profiles/list.html",
        context={"title": "Mapping-Profile", "active_nav": "mapping_profiles", "profiles": profiles},
    )


@router.get("/new", response_class=HTMLResponse)
def new_profile_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="mapping_profiles/new_step1.html",
        context={"title": "Neues Mapping-Profil", "active_nav": "mapping_profiles"},
    )


@router.post("/new", response_class=HTMLResponse)
async def upload_sample_csv(
    request: Request,
    name: str = Form(...),
    csv_file: UploadFile = File(...),
) -> HTMLResponse:
    raw = await csv_file.read()
    if not raw:
        return templates.TemplateResponse(
            request=request,
            name="mapping_profiles/new_step1.html",
            context={
                "title": "Neues Mapping-Profil",
                "active_nav": "mapping_profiles",
                "form_error": "Die hochgeladene Datei ist leer.",
                "name": name,
            },
            status_code=400,
        )

    TMP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    upload_id = uuid.uuid4().hex
    _upload_path(upload_id).write_bytes(raw)

    result = analyze(raw)
    preview_rows = build_preview_rows(
        result.header,
        result.sample_rows,
        result.date_format,
        result.decimal_separator,
        **result.column_guess,
    )

    return templates.TemplateResponse(
        request=request,
        name="mapping_profiles/new_step2.html",
        context=_step2_context(
            upload_id=upload_id,
            name=name,
            encoding=result.encoding,
            delimiter=result.delimiter,
            decimal_separator=result.decimal_separator,
            date_format=result.date_format,
            header_row_index=result.header_row_index,
            raw_preview_lines=result.raw_preview_lines,
            header=result.header,
            mapping=result.column_guess,
            preview_rows=preview_rows,
            parse_error=None,
        ),
    )


@router.post("/new/preview", response_class=HTMLResponse)
def preview_sample_csv(
    request: Request,
    upload_id: str = Form(...),
    delimiter: str = Form(","),
    decimal_separator: str = Form("."),
    encoding: str = Form("utf-8"),
    date_format: str = Form("%Y-%m-%d"),
    header_row_index: int = Form(0),
    date_column: str = Form(""),
    payee_column: str = Form(""),
    purpose_column: str = Form(""),
    amount_column: str = Form(""),
) -> HTMLResponse:
    header_row_index = max(0, header_row_index)
    upload_path = _upload_path(upload_id)
    mapping = _clean_mapping(
        {
            "date_column": date_column,
            "payee_column": payee_column,
            "purpose_column": purpose_column,
            "amount_column": amount_column,
        }
    )

    if not upload_path.exists():
        return templates.TemplateResponse(
            request=request,
            name="mapping_profiles/_step2_dynamic.html",
            context={
                "encoding": encoding,
                "delimiter": delimiter,
                "decimal_separator": decimal_separator,
                "date_format": date_format,
                "header_row_index": header_row_index,
                "raw_preview_lines": [],
                "header": [],
                "mapping": mapping,
                "preview_rows": [],
                "parse_error": "Die Beispiel-CSV ist nicht mehr verfügbar. Bitte Profil-Erstellung neu starten.",
                "mapping_fields": MAPPING_FIELDS,
                "mapping_labels": MAPPING_LABELS,
            },
        )

    raw = upload_path.read_bytes()
    raw_preview_lines = decode_lines(raw, encoding, limit=RAW_PREVIEW_LINE_LIMIT)
    header, rows = reparse_for_preview(raw, encoding, delimiter, header_row_index)
    # Falls Trennzeichen/Encoding/Kopfzeile gewechselt wurden, existieren zuvor
    # gewählte Spalten evtl. nicht mehr - Auswahl dann verwerfen statt eine
    # ungültige Zuordnung stehen zu lassen.
    for key, value in mapping.items():
        if value and value not in header:
            mapping[key] = None

    preview_rows = build_preview_rows(
        header, rows, date_format, decimal_separator, **mapping
    )
    parse_error = "CSV konnte mit diesen Einstellungen nicht gelesen werden." if not header else None

    return templates.TemplateResponse(
        request=request,
        name="mapping_profiles/_step2_dynamic.html",
        context={
            "encoding": encoding,
            "delimiter": delimiter,
            "decimal_separator": decimal_separator,
            "date_format": date_format,
            "header_row_index": header_row_index,
            "raw_preview_lines": raw_preview_lines,
            "header": header,
            "mapping": mapping,
            "preview_rows": preview_rows,
            "parse_error": parse_error,
            "mapping_fields": MAPPING_FIELDS,
            "mapping_labels": MAPPING_LABELS,
        },
    )


@router.post("", response_class=HTMLResponse)
def create_profile(
    request: Request,
    upload_id: str = Form(...),
    name: str = Form(...),
    delimiter: str = Form(","),
    decimal_separator: str = Form("."),
    encoding: str = Form("utf-8"),
    date_format: str = Form("%Y-%m-%d"),
    header_row_index: int = Form(0),
    date_column: str = Form(""),
    payee_column: str = Form(""),
    purpose_column: str = Form(""),
    amount_column: str = Form(""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    header_row_index = max(0, header_row_index)
    upload_path = _upload_path(upload_id)
    mapping = _clean_mapping(
        {
            "date_column": date_column,
            "payee_column": payee_column,
            "purpose_column": purpose_column,
            "amount_column": amount_column,
        }
    )

    def _rerender(error: str, status_code: int = 400) -> HTMLResponse:
        header, rows, raw_preview_lines = [], [], []
        if upload_path.exists():
            raw = upload_path.read_bytes()
            raw_preview_lines = decode_lines(raw, encoding, limit=RAW_PREVIEW_LINE_LIMIT)
            header, rows = reparse_for_preview(raw, encoding, delimiter, header_row_index)
        preview_rows = build_preview_rows(header, rows, date_format, decimal_separator, **mapping)
        return templates.TemplateResponse(
            request=request,
            name="mapping_profiles/new_step2.html",
            context=_step2_context(
                upload_id=upload_id,
                name=name,
                encoding=encoding,
                delimiter=delimiter,
                decimal_separator=decimal_separator,
                date_format=date_format,
                header_row_index=header_row_index,
                raw_preview_lines=raw_preview_lines,
                header=header,
                mapping=mapping,
                preview_rows=preview_rows,
                parse_error=None,
                form_error=error,
            ),
            status_code=status_code,
        )

    missing = [MAPPING_LABELS[key] for key in MAPPING_FIELDS if not mapping[key]]
    if missing:
        return _rerender(f"Bitte allen Feldern eine Spalte zuordnen (fehlt: {', '.join(missing)}).")

    profile = MappingProfile(
        name=name.strip(),
        delimiter=delimiter,
        decimal_separator=decimal_separator,
        encoding=encoding,
        date_format=date_format.strip(),
        header_row_index=header_row_index,
        date_column=mapping["date_column"],
        payee_column=mapping["payee_column"],
        purpose_column=mapping["purpose_column"],
        amount_column=mapping["amount_column"],
    )
    session.add(profile)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return _rerender(f"Ein Mapping-Profil mit dem Namen \"{name.strip()}\" existiert bereits.")

    upload_path.unlink(missing_ok=True)
    return RedirectResponse(url="/mapping-profiles", status_code=303)


@router.get("/{profile_id}/edit", response_class=HTMLResponse)
def edit_profile_form(
    request: Request, profile_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    profile = session.get(MappingProfile, profile_id)
    return templates.TemplateResponse(
        request=request,
        name="mapping_profiles/edit.html",
        context={"title": "Mapping-Profil bearbeiten", "active_nav": "mapping_profiles", "profile": profile},
    )


@router.post("/{profile_id}/edit", response_class=HTMLResponse)
def update_profile(
    request: Request,
    profile_id: int,
    name: str = Form(...),
    delimiter: str = Form(","),
    decimal_separator: str = Form("."),
    encoding: str = Form("utf-8"),
    date_format: str = Form("%Y-%m-%d"),
    header_row_index: int = Form(0),
    date_column: str = Form(...),
    payee_column: str = Form(...),
    purpose_column: str = Form(...),
    amount_column: str = Form(...),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    profile = session.get(MappingProfile, profile_id)
    fields = _form_to_fields(
        name, delimiter, decimal_separator, encoding, date_format, header_row_index,
        date_column, payee_column, purpose_column, amount_column,
    )
    for key, value in fields.items():
        setattr(profile, key, value)
    session.add(profile)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return templates.TemplateResponse(
            request=request,
            name="mapping_profiles/edit.html",
            context={
                "title": "Mapping-Profil bearbeiten",
                "active_nav": "mapping_profiles",
                "profile": profile,
                "form_error": f"Ein Mapping-Profil mit dem Namen \"{fields['name']}\" existiert bereits.",
            },
            status_code=400,
        )
    return RedirectResponse(url="/mapping-profiles", status_code=303)


@router.post("/{profile_id}/delete", response_class=HTMLResponse)
def delete_profile(
    request: Request, profile_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    profile = session.get(MappingProfile, profile_id)
    session.delete(profile)
    session.commit()
    return HTMLResponse(content="")
