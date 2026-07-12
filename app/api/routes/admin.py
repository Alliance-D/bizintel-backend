from fastapi import APIRouter, Depends, HTTPException, Request

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
from app.services.audit_service import write_audit_log

router = APIRouter()


def _audit(request: Request, db: Session, user: dict, action: str, entity_type: str | None = None, entity_id: str | None = None, metadata: dict | None = None) -> None:
    """Write an audit-log entry for an admin action and commit it."""
    write_audit_log(
        db, action=action, user=user, entity_type=entity_type, entity_id=entity_id, metadata=metadata,
        request_id=getattr(request.state, 'request_id', None),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get('user-agent'),
    )
    db.commit()


@router.get('/status')
def admin_status(db: Session = Depends(get_db), user: dict = Depends(require_min_role('admin'))) -> dict:
    """Pipeline readiness overview: data, features, predictions, active model and next steps."""
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
    """Return per-table row counts and readiness checks for the data pipeline."""
    return data_health(db)


@router.get('/jobs/status')
def admin_job_status(user: dict = Depends(require_min_role('admin'))) -> dict:
    """Return the status of the current background job (retrain/rebuild), if any."""
    return job_status()


@router.post('/jobs/retrain')
def admin_trigger_retrain(request: Request, activate: bool = True, db: Session = Depends(get_db), user: dict = Depends(require_min_role('admin'))) -> dict:
    """Kick off a model retrain-and-score job (409 if one is already running)."""
    result = trigger_retrain(activate=activate)
    if not result["started"]:
        raise HTTPException(status_code=409, detail=result["message"])
    _audit(request, db, user, action='model.retrain_triggered', metadata={'activate': activate})
    return result


@router.post('/jobs/rebuild-features')
def admin_trigger_grid_rebuild(request: Request, db: Session = Depends(get_db), user: dict = Depends(require_min_role('admin'))) -> dict:
    """Kick off a grid feature-table rebuild job (409 if one is already running)."""
    result = trigger_grid_rebuild()
    if not result["started"]:
        raise HTTPException(status_code=409, detail=result["message"])
    _audit(request, db, user, action='features.rebuild_triggered')
    return result


@router.post('/models/{model_version_id}/activate')
def admin_activate_model(model_version_id: int, request: Request, db: Session = Depends(get_db), user: dict = Depends(require_min_role('super_admin'))) -> dict:
    """Activate a specific trained model version (super-admin only)."""
    result = activate_model_version(db, model_version_id)
    if not result["activated"]:
        raise HTTPException(status_code=409, detail=result["message"])
    _audit(request, db, user, action='model.activated', entity_type='model_version', entity_id=str(model_version_id))
    return result
