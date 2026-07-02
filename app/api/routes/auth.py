from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.auth import RegisterRequest, LoginRequest
from app.services.auth_service import create_access_token, create_user, authenticate_user, current_user

router = APIRouter()

@router.post('/register')
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> dict:
    try:
        user = create_user(db, payload.model_dump())
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail='Could not create user. Email may already exist.') from exc
    token = create_access_token(str(user['id']), user['role'])
    return {'access_token': token, 'token_type': 'bearer', 'user': user}

@router.post('/login')
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    user = authenticate_user(db, payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid email or password')
    token = create_access_token(str(user['id']), user['role'])
    return {'access_token': token, 'token_type': 'bearer', 'user': user}

@router.get('/me')
def me(user: dict = Depends(current_user)) -> dict:
    return {'user': user}
