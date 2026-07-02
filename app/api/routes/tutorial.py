from __future__ import annotations

from fastapi import APIRouter, Query
from app.services.i18n_service import get_tutorial

router = APIRouter()


@router.get('/tutorial')
def tutorial(locale: str = Query('en')) -> dict:
    return get_tutorial(locale)
