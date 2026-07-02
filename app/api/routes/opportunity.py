from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.product import OpportunityMapQuery
from app.services.opportunity_service import list_opportunity_cells, summarize_opportunity_map
router = APIRouter()
@router.get('/summary')
def opportunity_summary(category: str = Query('salon'), district: str | None = None, db: Session = Depends(get_db)) -> dict:
    cells = list_opportunity_cells(db, category=category, district=district, limit=50)
    return {'category': category, 'district': district, 'summary': summarize_opportunity_map(cells), 'top_cells': cells[:10]}
@router.post('/query')
def query_opportunity_map(payload: OpportunityMapQuery, db: Session = Depends(get_db)) -> dict:
    cells = list_opportunity_cells(db, category=payload.business_category, district=payload.district, limit=payload.limit)
    return {'mode': payload.mode, 'business_category': payload.business_category, 'district': payload.district, 'cells': cells, 'summary': summarize_opportunity_map(cells)}
@router.get('/tiles/{z}/{x}/{y}')
def opportunity_tiles(z: int, x: int, y: int, category: str = Query('salon')) -> dict:
    return {'type': 'FeatureCollection', 'features': [], 'meta': {'category': category, 'z': z, 'x': x, 'y': y, 'message': 'Use vector tiles in Phase 5.'}}
