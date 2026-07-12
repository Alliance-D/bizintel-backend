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
    """Most recent audit-log events, newest first (admin only)."""
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
    db: Session = Depends(get_db),
    user: dict = Depends(require_min_role('admin')),
) -> dict:
    """Activity counts by action, from the audit log. Per-route latency tracking
    is not implemented yet - this reports what is actually recorded today."""
    rows = db.execute(text('''
        SELECT action, COUNT(*) AS event_count, MAX(created_at) AS last_seen
        FROM app.audit_log
        GROUP BY action
        ORDER BY event_count DESC
    ''')).mappings().all()
    return {'activity_by_action': [dict(row) for row in rows]}
