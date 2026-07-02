from fastapi import APIRouter, Depends, HTTPException

from sqlalchemy.orm import Session

from app.core.security import require_min_role
from app.db.session import get_db
from app.data.catalog_service import data_health
from app.ml.model_registry import model_status
from app.services.admin_jobs_service import (
    activate_model_version,
    job_status,
    trigger_grid_rebuild,
    trigger_retrain,
)

router = APIRouter()


@router.get('/status')
def admin_status(db: Session = Depends(get_db), user: dict = Depends(require_min_role('admin'))) -> dict:
    health = data_health(db)
    model = model_status(db)
    feature_rows = health['checks'].get('grid_category_feature_rows') or 0
    prediction_rows = health['checks'].get('ml_predictions') or 0
    return {
        'data': 'ready' if health['checks'].get('osm_pois') else 'waiting_for_imports',
        'features': 'ready' if feature_rows > 0 else 'waiting_for_feature_generation',
        'predictions': 'ready' if prediction_rows > 0 else 'waiting_for_scoring',
        'model': model,
        'data_health': health,
        'job': job_status(),
        'next_steps': [] if health['ready_for_training'] else [
            'Import or connect real data layers.',
            'Generate grid-category feature tables.',
            'Train and activate the best ML model.',
        ],
    }


@router.get('/data-health')
def admin_data_health(db: Session = Depends(get_db), user: dict = Depends(require_min_role('admin'))) -> dict:
    return data_health(db)


@router.get('/jobs/status')
def admin_job_status(user: dict = Depends(require_min_role('admin'))) -> dict:
    return job_status()


@router.post('/jobs/retrain')
def admin_trigger_retrain(activate: bool = True, user: dict = Depends(require_min_role('admin'))) -> dict:
    result = trigger_retrain(activate=activate)
    if not result["started"]:
        raise HTTPException(status_code=409, detail=result["message"])
    return result


@router.post('/jobs/rebuild-features')
def admin_trigger_grid_rebuild(user: dict = Depends(require_min_role('admin'))) -> dict:
    result = trigger_grid_rebuild()
    if not result["started"]:
        raise HTTPException(status_code=409, detail=result["message"])
    return result


@router.post('/models/{model_version_id}/activate')
def admin_activate_model(model_version_id: int, db: Session = Depends(get_db), user: dict = Depends(require_min_role('super_admin'))) -> dict:
    result = activate_model_version(db, model_version_id)
    if not result["activated"]:
        raise HTTPException(status_code=409, detail=result["message"])
    return result
