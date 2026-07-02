from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.live import LocationContextRequest
from app.services.live_layer_service import (
    get_data_readiness,
    get_location_context,
    list_available_layers,
    list_opportunity_points,
)

router = APIRouter()


@router.get("/data-readiness")
def data_readiness(db: Session = Depends(get_db)) -> dict:
    return get_data_readiness(db)


@router.get("/layers")
def layers(db: Session = Depends(get_db)) -> dict:
    return list_available_layers(db)


@router.post("/location-context")
def location_context(payload: LocationContextRequest, db: Session = Depends(get_db)) -> dict:
    return get_location_context(
        db,
        latitude=payload.latitude,
        longitude=payload.longitude,
        business_category=payload.business_category,
        radius_meters=payload.radius_meters,
    )


@router.get("/opportunity-points")
def opportunity_points(category: str = Query("salon"), limit: int = Query(500, ge=10, le=5000), db: Session = Depends(get_db)) -> dict:
    return list_opportunity_points(db, category=category, limit=limit)
