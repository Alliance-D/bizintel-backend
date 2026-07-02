from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import require_min_role
from app.db.session import get_db
from app.ml.model_registry import (
    list_feature_importance,
    list_model_metrics,
    list_model_versions,
    model_status,
)

router = APIRouter()


@router.get("/models/status")
def get_model_status(db: Session = Depends(get_db), user: dict = Depends(require_min_role('admin'))) -> dict:
    return model_status(db)


@router.get("/models/versions")
def get_model_versions(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), user: dict = Depends(require_min_role('admin'))) -> dict:
    return {"models": list_model_versions(db, limit=limit)}


@router.get("/models/metrics")
def get_metrics(model_version_id: int | None = None, limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db), user: dict = Depends(require_min_role('admin'))) -> dict:
    return {"metrics": list_model_metrics(db, model_version_id=model_version_id, limit=limit)}


@router.get("/models/feature-importance")
def get_feature_importance(model_version_id: int | None = None, limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db), user: dict = Depends(require_min_role('admin'))) -> dict:
    return {"features": list_feature_importance(db, model_version_id=model_version_id, limit=limit)}
