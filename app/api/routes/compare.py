from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.product import CompareLocationsRequest
from app.services.comparison_service import compare_locations
router = APIRouter()
@router.post('/locations')
def compare_candidate_locations(payload: CompareLocationsRequest, db: Session = Depends(get_db)) -> dict:
    return compare_locations(db, payload.business_category, [loc.model_dump() for loc in payload.locations])
