from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.database import get_session
from app.models import Category, Transaction
from app.templating import templates

router = APIRouter(prefix="/categories", tags=["categories"])


def _top_level_categories(session: Session) -> list[Category]:
    return session.exec(
        select(Category).where(Category.parent_id.is_(None)).order_by(Category.name)
    ).all()


def _list_context(session: Session, **extra) -> dict:
    top_level = _top_level_categories(session)
    children_by_parent: dict[int, list[Category]] = {}
    for cat in top_level:
        children_by_parent[cat.id] = session.exec(
            select(Category).where(Category.parent_id == cat.id).order_by(Category.name)
        ).all()
    return {
        "title": "Kategorien",
        "active_nav": "categories",
        "top_level": top_level,
        "children_by_parent": children_by_parent,
        **extra,
    }


@router.get("", response_class=HTMLResponse)
def list_categories(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="categories/list.html",
        context=_list_context(session),
    )


@router.post("", response_class=HTMLResponse)
def create_category(
    request: Request,
    name: str = Form(...),
    parent_id: str = Form(""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    category = Category(
        name=name.strip(),
        parent_id=int(parent_id) if parent_id else None,
    )
    session.add(category)
    session.commit()
    return RedirectResponse(url="/categories", status_code=303)


@router.get("/{category_id}/edit", response_class=HTMLResponse)
def edit_category_form(
    request: Request, category_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    category = session.get(Category, category_id)
    top_level = [c for c in _top_level_categories(session) if c.id != category_id]
    return templates.TemplateResponse(
        request=request,
        name="categories/edit.html",
        context={
            "title": "Kategorie bearbeiten",
            "active_nav": "categories",
            "category": category,
            "top_level": top_level,
        },
    )


@router.post("/{category_id}/edit", response_class=HTMLResponse)
def update_category(
    request: Request,
    category_id: int,
    name: str = Form(...),
    parent_id: str = Form(""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    category = session.get(Category, category_id)
    new_parent_id = int(parent_id) if parent_id else None

    if new_parent_id == category_id:
        top_level = [c for c in _top_level_categories(session) if c.id != category_id]
        return templates.TemplateResponse(
            request=request,
            name="categories/edit.html",
            context={
                "title": "Kategorie bearbeiten",
                "active_nav": "categories",
                "category": category,
                "top_level": top_level,
                "form_error": "Eine Kategorie kann nicht ihre eigene Oberkategorie sein.",
            },
            status_code=400,
        )

    category.name = name.strip()
    category.parent_id = new_parent_id
    session.add(category)
    session.commit()
    return RedirectResponse(url="/categories", status_code=303)


@router.post("/{category_id}/delete", response_class=HTMLResponse)
def delete_category(
    request: Request, category_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    has_children = session.exec(
        select(Category).where(Category.parent_id == category_id).limit(1)
    ).first()
    has_transactions = session.exec(
        select(Transaction).where(Transaction.category_id == category_id).limit(1)
    ).first()
    if has_children or has_transactions:
        return HTMLResponse(
            content='<span class="text-xs text-red-600 dark:text-red-400">Wird noch verwendet - kann nicht gelöscht werden.</span>',
            status_code=409,
        )

    category = session.get(Category, category_id)
    session.delete(category)
    session.commit()
    return HTMLResponse(content="")
