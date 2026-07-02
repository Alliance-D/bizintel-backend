from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.data.catalog_service import data_health
from app.ml.model_registry import model_status

router = APIRouter()


@router.get('/status')
def admin_status(db: Session = Depends(get_db)) -> dict:
    health = data_health(db)
    model = model_status(db)
    feature_rows = health['checks'].get('training_feature_rows') or 0
    catalog_rows = health['checks'].get('dataset_catalog_rows') or 0
    return {
        'data': 'ready' if catalog_rows > 0 else 'waiting_for_imports',
        'features': 'ready' if feature_rows > 0 else 'waiting_for_feature_generation',
        'model': model,
        'data_health': health,
        'next_steps': [
            'Import or connect real data layers.',
            'Generate grid-category feature tables.',
            'Train and activate the best ML model.',
        ],
    }


@router.get('/data-health')
def admin_data_health(db: Session = Depends(get_db)) -> dict:
    return data_health(db)
