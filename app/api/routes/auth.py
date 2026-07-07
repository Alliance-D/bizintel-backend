from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from app.core.rate_limit import limiter
from app.core.security import role_level
from app.db.session import get_db
from app.schemas.auth import RegisterRequest, LoginRequest
from app.services.auth_service import create_access_token, create_user, authenticate_user, current_user
from app.services.audit_service import write_audit_log

router = APIRouter()

@router.post('/register')
@limiter.limit('5/minute')
def register(request: Request, payload: RegisterRequest, db: Session = Depends(get_db)) -> dict:
    try:
        user = create_user(db, payload.model_dump())
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail='Could not create user. Email may already exist.') from exc
    token = create_access_token(str(user['id']), user['role'])
    return {'access_token': token, 'token_type': 'bearer', 'user': user}

@router.post('/login')
@limiter.limit('10/minute')
def login(request: Request, payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    user = authenticate_user(db, payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid email or password')
    if role_level(user['role']) >= role_level('admin'):
        write_audit_log(db, action='auth.admin_login', user=user, entity_type='user', entity_id=str(user['id']), request_id=getattr(request.state, 'request_id', None), ip_address=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'))
        db.commit()
    token = create_access_token(str(user['id']), user['role'])
    return {'access_token': token, 'token_type': 'bearer', 'user': user}

@router.get('/me')
def me(user: dict = Depends(current_user)) -> dict:
    return {'user': user}

@router.post('/refresh')
def refresh(user: dict = Depends(current_user)) -> dict:
    """Reissue a fresh token for the current session. Requires a still-valid token."""
    token = create_access_token(str(user['id']), user['role'])
    return {'access_token': token, 'token_type': 'bearer', 'user': user}
