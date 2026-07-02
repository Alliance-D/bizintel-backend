from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import require_min_role
from app.db.session import get_db
from app.data.catalog_service import data_health
from app.ml.model_registry import model_status

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
        'next_steps': [] if health['ready_for_training'] else [
            'Import or connect real data layers.',
            'Generate grid-category feature tables.',
            'Train and activate the best ML model.',
        ],
    }


@router.get('/data-health')
def admin_data_health(db: Session = Depends(get_db), user: dict = Depends(require_min_role('admin'))) -> dict:
    return data_health(db)
