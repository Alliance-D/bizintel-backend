from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.validation import ValidationPointCreate
from app.services.field_validation_service import create_validation_point, list_validation_points

router = APIRouter()

@router.post('/points')
def submit_validation_point(payload: ValidationPointCreate, db: Session = Depends(get_db)) -> dict:
    point = create_validation_point(db, payload.model_dump())
    return {'validation_point': point}

@router.get('/points')
def validation_points(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)) -> dict:
    return {'validation_points': list_validation_points(db, limit=limit)}
