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
    """Report whether the AI advisor (Gemini) is configured on this deployment."""
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


def _clean_user_context(raw: object) -> dict[str, str] | None:
    """Defensive parsing for optional user-stated context - never fed to the
    model, only ever used to personalize the advisor's narrative tone."""
    if not isinstance(raw, dict):
        return None
    budget = str(raw.get('budget') or '')[:300].strip()
    notes = str(raw.get('notes') or '')[:500].strip()
    if not budget and not notes:
        return None
    return {"budget": budget, "notes": notes}


@router.post('/advisor')
@limiter.limit('30/minute')
def advisor(request: Request, payload: dict, db: Session = Depends(get_db)) -> dict:
    """Assess a point, then return AI narrative advice for it (rate limited).

    Accepts optional prior ``messages`` for follow-up questions and optional
    user-stated ``user_context`` used only to personalize the narrative's tone.
    """
    category = normalise_category(payload.get('business_category') or payload.get('category') or 'pharmacy')
    latitude = float(payload.get('latitude'))
    longitude = float(payload.get('longitude'))
    history = _clean_history(payload.get('messages'))
    user_context = _clean_user_context(payload.get('user_context'))
    assessment = assess_location_ml(db, latitude=latitude, longitude=longitude, business_category=category)
    result = generate_advice(assessment, locale=payload.get('locale'), history=history, user_context=user_context)
    return {
        "business_category": category,
        "latitude": latitude,
        "longitude": longitude,
        **result,
    }
