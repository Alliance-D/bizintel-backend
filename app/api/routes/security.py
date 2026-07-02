from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import require_min_role
from app.db.session import get_db

router = APIRouter()


@router.get('/audit-log')
def audit_log(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: dict = Depends(require_min_role('admin')),
) -> dict:
    rows = db.execute(text('''
        SELECT id, actor_user_id, actor_role, action, entity_type, entity_id,
               request_id, metadata, created_at
        FROM app.audit_log
        ORDER BY created_at DESC
        LIMIT :limit
    '''), {'limit': limit}).mappings().all()
    return {'events': [dict(row) for row in rows]}


@router.get('/usage')
def api_usage(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: dict = Depends(require_min_role('admin')),
) -> dict:
    rows = db.execute(text('''
        SELECT route, method, status_code, latency_ms, request_id, created_at
        FROM app.api_usage_events
        ORDER BY created_at DESC
        LIMIT :limit
    '''), {'limit': limit}).mappings().all()
    return {'events': [dict(row) for row in rows]}
