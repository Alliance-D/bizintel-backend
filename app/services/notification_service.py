from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def list_notifications(db: Session, limit: int = 30) -> list[dict]:
    try:
        rows = db.execute(text("""
            SELECT id, title, COALESCE(body, message) AS body, alert_type, severity, created_at, saved_location_id
            FROM app.alerts
            WHERE saved_location_id IS NOT NULL
            ORDER BY created_at DESC
            LIMIT :limit
        """), {"limit": limit}).mappings().all()
        return [dict(row) for row in rows]
    except Exception:
        db.rollback()
        return []


def upsert_preferences(db: Session, user_id: int, payload: dict) -> dict:
    try:
        row = db.execute(text("""
            INSERT INTO app.notification_preferences (
              user_id, weekly_digest, opportunity_alerts, competition_alerts, email_enabled, updated_at
            ) VALUES (
              :user_id, :weekly_digest, :opportunity_alerts, :competition_alerts, :email_enabled, now()
            )
            ON CONFLICT (user_id) DO UPDATE SET
              weekly_digest = EXCLUDED.weekly_digest,
              opportunity_alerts = EXCLUDED.opportunity_alerts,
              competition_alerts = EXCLUDED.competition_alerts,
              email_enabled = EXCLUDED.email_enabled,
              updated_at = now()
            RETURNING *
        """), {"user_id": user_id, **payload}).mappings().first()
        db.commit()
        return dict(row)
    except Exception:
        db.rollback()
        return {"user_id": user_id, **payload, "status": "not_saved"}
