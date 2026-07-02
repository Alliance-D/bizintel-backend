from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import require_min_role
from app.db.session import get_db
from app.data.catalog_service import list_datasets

router = APIRouter()


@router.get("/datasets/catalog")
def dataset_catalog(limit: int = Query(200, ge=1, le=500), db: Session = Depends(get_db), user: dict = Depends(require_min_role('admin'))) -> dict:
    return {"datasets": list_datasets(db, limit=limit)}
