import json
from sqlalchemy import text
from sqlalchemy.orm import Session

# The IP address and user-agent on an audit row are network/device locators -
# personal data - while the rest of the row (who, what, when) is the security
# trail we want to keep indefinitely. The privacy policy commits to a 30-day
# window for the locators, so past that we null just those two columns and leave
# the accountability record intact. This is data minimisation, not log deletion.
AUDIT_LOCATOR_RETENTION_DAYS = 30


def _purge_expired_audit_locators(db: Session) -> None:
    """Null the IP/user-agent on audit rows past the retention window. Runs in a
    savepoint so a purge failure can never roll back the audit write it rides
    along with. The created_at index keeps the guarded scan cheap."""
    try:
        with db.begin_nested():
            db.execute(text('''
                UPDATE app.audit_log
                SET ip_address = NULL, user_agent = NULL
                WHERE created_at < now() - make_interval(days => :days)
                  AND (ip_address IS NOT NULL OR user_agent IS NOT NULL)
            '''), {'days': AUDIT_LOCATOR_RETENTION_DAYS})
    except Exception:
        pass


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
    """Insert an audit-log row capturing who did what, from where. Also runs an
    opportunistic purge so IP/user-agent on rows older than the retention window
    are nulled on the same low-frequency path that writes new entries."""
    _purge_expired_audit_locators(db)
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
