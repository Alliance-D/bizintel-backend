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


@router.post('/advisor')
@limiter.limit('20/minute')
def advisor(request: Request, payload: dict, db: Session = Depends(get_db)) -> dict:
    category = normalise_category(payload.get('business_category') or payload.get('category') or 'pharmacy')
    latitude = float(payload.get('latitude'))
    longitude = float(payload.get('longitude'))
    assessment = assess_location_ml(db, latitude=latitude, longitude=longitude, business_category=category)
    result = generate_advice(assessment)
    return {
        "business_category": category,
        "latitude": latitude,
        "longitude": longitude,
        **result,
    }
