from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.experience import CellInsightRequest, ExperienceEventRequest
from app.services.experience_service import (
    get_cell_insight,
    get_category_story,
    get_experience_manifest,
    get_recommendation_feed,
    track_experience_event,
)

router = APIRouter()


@router.get('/manifest')
def manifest(db: Session = Depends(get_db)) -> dict:
    return get_experience_manifest(db)


@router.post('/cell-insight')
def cell_insight(payload: CellInsightRequest, db: Session = Depends(get_db)) -> dict:
    return get_cell_insight(
        db,
        latitude=payload.latitude,
        longitude=payload.longitude,
        business_category=payload.business_category,
        radius_meters=payload.radius_meters,
    )


@router.get('/category-story')
def category_story(category: str = Query('salon'), db: Session = Depends(get_db)) -> dict:
    return get_category_story(db, business_category=category)


@router.get('/recommendation-feed')
def recommendation_feed(category: str = Query('salon'), limit: int = Query(12, ge=1, le=50), db: Session = Depends(get_db)) -> dict:
    return get_recommendation_feed(db, business_category=category, limit=limit)


@router.post('/events')
def events(payload: ExperienceEventRequest, db: Session = Depends(get_db)) -> dict:
    return track_experience_event(
        db,
        event_name=payload.event_name,
        business_category=payload.business_category,
        latitude=payload.latitude,
        longitude=payload.longitude,
        payload=payload.payload,
        session_id=payload.session_id,
    )
