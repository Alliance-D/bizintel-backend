import json
from sqlalchemy import text
from sqlalchemy.orm import Session


def write_audit_log(
    db: Session,
    *,
    action: str,
    user: dict | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    request_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict | None = None,
) -> None:
    db.execute(text('''
        INSERT INTO app.audit_log (
            actor_user_id, actor_role, action, entity_type, entity_id,
            request_id, ip_address, user_agent, metadata
        ) VALUES (
            :actor_user_id, :actor_role, :action, :entity_type, :entity_id,
            :request_id, CAST(:ip_address AS inet), :user_agent, CAST(:metadata AS jsonb)
        )
    '''), {
        'actor_user_id': user.get('id') if user else None,
        'actor_role': user.get('role') if user else None,
        'action': action,
        'entity_type': entity_type,
        'entity_id': entity_id,
        'request_id': request_id,
        'ip_address': ip_address,
        'user_agent': user_agent,
        'metadata': json.dumps(metadata or {}),
    })
