from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.data.catalog_service import list_features

router = APIRouter()


@router.get("/features/catalog")
def feature_catalog(limit: int = Query(300, ge=1, le=1000), db: Session = Depends(get_db)) -> dict:
    return {"features": list_features(db, limit=limit)}
