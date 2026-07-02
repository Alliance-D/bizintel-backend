from collections.abc import Callable
from fastapi import Depends, HTTPException, status
from app.services.auth_service import current_user

ROLE_ORDER = {
    'entrepreneur': 10,
    'advisor': 20,
    'researcher': 25,
    'admin': 50,
    'super_admin': 100,
}


def role_level(role: str) -> int:
    return ROLE_ORDER.get(role, 0)


def require_roles(*allowed_roles: str) -> Callable:
    allowed = set(allowed_roles)

    def dependency(user: dict = Depends(current_user)) -> dict:
        if user.get('role') not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Insufficient permissions')
        return user

    return dependency


def require_min_role(min_role: str) -> Callable:
    min_level = role_level(min_role)

    def dependency(user: dict = Depends(current_user)) -> dict:
        if role_level(user.get('role', '')) < min_level:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Insufficient permissions')
        return user

    return dependency
