from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.location import ScoutAssessmentRequest, ScoutAssessmentResponse
from app.geo.feature_extraction import extract_location_features
from app.ml.inference import predict_opportunity
from app.services.explanation_service import build_explanations

router = APIRouter()


@router.post("/assess", response_model=ScoutAssessmentResponse)
def assess_location(payload: ScoutAssessmentRequest, db: Session = Depends(get_db)):
    features = extract_location_features(
        db=db,
        latitude=payload.latitude,
        longitude=payload.longitude,
        business_category=payload.business_category,
        radius_meters=payload.radius_meters,
    )
    prediction = predict_opportunity(features, payload.business_category, db=db)
    explanation = build_explanations(features)

    return ScoutAssessmentResponse(
        opportunity_score=prediction["score"],
        category=payload.business_category,
        opportunity_type=prediction["opportunity_type"],
        confidence=prediction["confidence"],
        factors=explanation["factors"],
        strengths=explanation["strengths"],
        risks=explanation["risks"],
        next_steps=explanation["next_steps"],
    )
