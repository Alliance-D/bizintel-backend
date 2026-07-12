from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.product import CompetitiveAnalysisRequest
from app.services.competitive_service import analyze_competition
router = APIRouter()
@router.post('/analyze')
def competitive_analysis(payload: CompetitiveAnalysisRequest, db: Session = Depends(get_db)) -> dict:
    """Analyze competitor density and nearby complementary businesses around a point."""
    return analyze_competition(db, payload.latitude, payload.longitude, payload.business_category, payload.radius_meters)
