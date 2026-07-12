from __future__ import annotations

from fastapi import APIRouter, Query
from app.services.i18n_service import get_translations

router = APIRouter()


@router.get('/i18n')
def i18n(locale: str = Query('en')) -> dict:
    """Return the UI translation bundle for a locale."""
    return get_translations(locale)
