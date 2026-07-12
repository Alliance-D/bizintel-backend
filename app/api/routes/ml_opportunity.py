from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.ml_opportunity import MLAssessRequest
from app.services.ml_opportunity_service import (
    assess_location_ml,
    get_ml_engine_status,
    list_category_profiles,
    list_top_opportunity_zones,
)

router = APIRouter()


@router.get("/status")
def status(db: Session = Depends(get_db)) -> dict:
    """Report ML engine readiness: prediction cache size, active model and coverage."""
    return get_ml_engine_status(db)


@router.get("/category-profiles")
def category_profiles(db: Session = Depends(get_db)) -> dict:
    """Return per-category summary profiles across the scored grid."""
    return list_category_profiles(db)


@router.post("/assess")
def assess(payload: MLAssessRequest, db: Session = Depends(get_db)) -> dict:
    """Assess a single point: snap to the nearest scored cell and recount competitors live."""
    return assess_location_ml(
        db,
        latitude=payload.latitude,
        longitude=payload.longitude,
        business_category=payload.business_category,
        radius_meters=payload.radius_meters,
    )


@router.get("/top-zones")
def top_zones(
    category: str = Query("salon"),
    limit: int = Query(25, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    """Return the top-ranked opportunity cells for a category."""
    return list_top_opportunity_zones(db, business_category=category, limit=limit)
