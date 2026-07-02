from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.product import SavedLocationCreate, WatchlistCreate
from app.services.watchlist_service import create_saved_location, delete_saved_location, list_alerts, list_saved_locations

router = APIRouter()

@router.get('/saved-locations')
def saved_locations(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)) -> dict:
    return {'locations': list_saved_locations(db, limit=limit), 'source': 'database'}

@router.post('/saved-locations')
def save_location(payload: SavedLocationCreate, db: Session = Depends(get_db)) -> dict:
    try:
        return {'location': create_saved_location(db, payload.model_dump()), 'source': 'database'}
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail='Could not save location to database') from exc


@router.delete('/saved-locations/{location_id}')
def remove_saved_location(location_id: int, db: Session = Depends(get_db)) -> dict:
    try:
        deleted = delete_saved_location(db, location_id)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail='Could not delete saved location') from exc
    if not deleted:
        raise HTTPException(status_code=404, detail='Saved location not found')
    return {'deleted': deleted, 'source': 'database'}

@router.get('/alerts')
def alerts(limit: int = Query(30, ge=1, le=100), db: Session = Depends(get_db)) -> dict:
    return {'alerts': list_alerts(db, limit=limit), 'source': 'database'}

@router.post('/watchlists')
def create_watchlist(payload: WatchlistCreate) -> dict:
    raise HTTPException(status_code=501, detail='Watchlist creation is not connected yet. Save locations from the map first.')
