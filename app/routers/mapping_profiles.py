from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.database import get_session
from app.models import MappingProfile

router = APIRouter(prefix="/mapping-profiles", tags=["mapping-profiles"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")


def _form_to_fields(
    name: str,
    delimiter: str,
    decimal_separator: str,
    encoding: str,
    date_format: str,
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


@router.post("", response_class=HTMLResponse)
def create_profile(
    request: Request,
    name: str = Form(...),
    delimiter: str = Form(","),
    decimal_separator: str = Form("."),
    encoding: str = Form("utf-8"),
    date_format: str = Form("%Y-%m-%d"),
    date_column: str = Form(...),
    payee_column: str = Form(...),
    purpose_column: str = Form(...),
    amount_column: str = Form(...),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    fields = _form_to_fields(
        name, delimiter, decimal_separator, encoding, date_format,
        date_column, payee_column, purpose_column, amount_column,
    )
    profile = MappingProfile(**fields)
    session.add(profile)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        profiles = session.exec(select(MappingProfile).order_by(MappingProfile.name)).all()
        return templates.TemplateResponse(
            request=request,
            name="mapping_profiles/list.html",
            context={
                "title": "Mapping-Profile",
                "active_nav": "mapping_profiles",
                "profiles": profiles,
                "form_error": f"Ein Mapping-Profil mit dem Namen \"{fields['name']}\" existiert bereits.",
                "form_data": fields,
            },
            status_code=400,
        )
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
    date_column: str = Form(...),
    payee_column: str = Form(...),
    purpose_column: str = Form(...),
    amount_column: str = Form(...),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    profile = session.get(MappingProfile, profile_id)
    fields = _form_to_fields(
        name, delimiter, decimal_separator, encoding, date_format,
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
