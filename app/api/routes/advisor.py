from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.categories import normalise_category
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.services.ai_advisor_service import generate_advice, is_available
from app.services.ml_opportunity_service import assess_location_ml

router = APIRouter()


@router.get('/advisor/status')
def advisor_status() -> dict:
    return {"available": is_available()}


def _clean_history(raw: object) -> list[dict[str, str]]:
    """Defensive parsing for the client-held conversation: cap length and size
    per message so a malformed or abusive payload can't blow up the prompt."""
    if not isinstance(raw, list):
        return []
    cleaned: list[dict[str, str]] = []
    for item in raw[-40:]:
        if not isinstance(item, dict):
            continue
        role = item.get('role') if item.get('role') in ('user', 'assistant') else 'user'
        text = str(item.get('text') or '')[:2000].strip()
        if text:
            cleaned.append({'role': role, 'text': text})
    return cleaned


@router.post('/advisor')
@limiter.limit('30/minute')
def advisor(request: Request, payload: dict, db: Session = Depends(get_db)) -> dict:
    category = normalise_category(payload.get('business_category') or payload.get('category') or 'pharmacy')
    latitude = float(payload.get('latitude'))
    longitude = float(payload.get('longitude'))
    history = _clean_history(payload.get('messages'))
    assessment = assess_location_ml(db, latitude=latitude, longitude=longitude, business_category=category)
    result = generate_advice(assessment, locale=payload.get('locale'), history=history)
    return {
        "business_category": category,
        "latitude": latitude,
        "longitude": longitude,
        **result,
    }
