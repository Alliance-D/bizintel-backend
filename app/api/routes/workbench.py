from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.workbench import SavedWorkbenchStateCreate, UserPreferencesUpdate
from app.services.auth_service import current_user
from app.services.workbench_state_service import (
    create_workbench_state,
    delete_workbench_state,
    get_or_create_preferences,
    list_workbench_states,
    update_preferences,
)
from app.services.audit_service import write_audit_log

router = APIRouter()


@router.get('/states')
def states(db: Session = Depends(get_db), user: dict = Depends(current_user)) -> dict:
    """List the current user's saved workbench states."""
    return {'states': list_workbench_states(db, int(user['id']))}


@router.post('/states', status_code=status.HTTP_201_CREATED)
def create_state(payload: SavedWorkbenchStateCreate, request: Request, db: Session = Depends(get_db), user: dict = Depends(current_user)) -> dict:
    """Save a workbench state for the current user and audit-log it."""
    state = create_workbench_state(db, int(user['id']), payload.model_dump())
    write_audit_log(db, action='workbench_state.created', user=user, entity_type='saved_workbench_state', entity_id=str(state['id']), request_id=getattr(request.state, 'request_id', None), ip_address=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'))
    db.commit()
    return {'state': state}


@router.delete('/states/{state_id}')
def remove_state(state_id: int, request: Request, db: Session = Depends(get_db), user: dict = Depends(current_user)) -> dict:
    """Delete one of the current user's saved workbench states (404 if missing)."""
    deleted = delete_workbench_state(db, int(user['id']), state_id)
    if not deleted:
        raise HTTPException(status_code=404, detail='Saved workbench state not found')
    write_audit_log(db, action='workbench_state.deleted', user=user, entity_type='saved_workbench_state', entity_id=str(state_id), request_id=getattr(request.state, 'request_id', None), ip_address=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'))
    db.commit()
    return {'deleted': True}


@router.get('/preferences')
def preferences(db: Session = Depends(get_db), user: dict = Depends(current_user)) -> dict:
    """Return the current user's preferences, creating defaults on first access."""
    return {'preferences': get_or_create_preferences(db, int(user['id']))}


@router.patch('/preferences')
def patch_preferences(payload: UserPreferencesUpdate, db: Session = Depends(get_db), user: dict = Depends(current_user)) -> dict:
    """Partially update the current user's preferences."""
    return {'preferences': update_preferences(db, int(user['id']), payload.model_dump(exclude_unset=True))}
