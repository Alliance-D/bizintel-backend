from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy import text
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.core.config import get_settings
from app.db.session import get_db

pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')
oauth2_scheme = OAuth2PasswordBearer(tokenUrl='/api/v1/auth/login')


def hash_password(password: str) -> str:
    """Hash a plaintext password for storage."""
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a stored hash."""
    return pwd_context.verify(password, password_hash)


def create_access_token(subject: str, role: str, minutes: int = 60 * 24) -> str:
    """Mint a signed JWT access token for a user id and role."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {'sub': subject, 'role': role, 'iat': now, 'exp': now + timedelta(minutes=minutes)}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_user(db: Session, payload: dict) -> dict:
    """Create a user account (hashing the password) and return it."""
    row = db.execute(text("""
        INSERT INTO app.users (full_name, email, password_hash, role)
        VALUES (:full_name, :email, :password_hash, :role)
        RETURNING id, full_name, email, role, created_at
    """), {
        'full_name': payload['full_name'],
        'email': payload['email'].lower(),
        'password_hash': hash_password(payload['password']),
        'role': payload.get('role', 'entrepreneur'),
    }).mappings().first()
    db.commit()
    return dict(row)


def authenticate_user(db: Session, email: str, password: str) -> dict | None:
    """Return the user when the email and password are valid, else None."""
    row = db.execute(text("""
        SELECT id, full_name, email, role, password_hash, is_active
        FROM app.users
        WHERE email = :email
    """), {'email': email.lower()}).mappings().first()
    if not row or not row['is_active']:
        return None
    if not verify_password(password, row['password_hash']):
        return None
    return {k: row[k] for k in ['id', 'full_name', 'email', 'role']}


def current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> dict:
    """FastAPI dependency resolving the authenticated user from the bearer token."""
    credentials_error = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid or expired token')
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=[get_settings().jwt_algorithm])
        user_id = int(payload.get('sub'))
    except (JWTError, TypeError, ValueError):
        raise credentials_error
    row = db.execute(text("""
        SELECT id, full_name, email, role, is_active
        FROM app.users
        WHERE id = :id
    """), {'id': user_id}).mappings().first()
    if not row or not row['is_active']:
        raise credentials_error
    return dict(row)
