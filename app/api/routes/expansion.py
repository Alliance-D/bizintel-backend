from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.categories import normalise_category
from app.db.session import get_db
from app.services.expansion_planner_service import plan_expansion

router = APIRouter()


@router.post('/expansion-planner')
def expansion_planner(payload: dict, db: Session = Depends(get_db)) -> dict:
    category = normalise_category(payload.get('business_category') or payload.get('category') or 'pharmacy')
    existing_locations = payload.get('existing_locations') or []
    limit = int(payload.get('limit') or 8)
    min_distance_m = int(payload.get('min_distance_from_existing_m') or 600)
    return plan_expansion(db, business_category=category, existing_locations=existing_locations, limit=limit, min_distance_from_existing_m=min_distance_m)
