from __future__ import annotations

from fastapi import APIRouter, Query
from app.core.categories import category_payload

router = APIRouter()


@router.get('/categories')
def get_categories(locale: str = Query('en')) -> list[dict]:
    return category_payload(locale)
