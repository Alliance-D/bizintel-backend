from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def create_validation_point(db: Session, payload: dict, user_id: int | None = None) -> dict:
    try:
        row = db.execute(text("""
            INSERT INTO field.validation_points (
              user_id, business_category, latitude, longitude, observed_activity,
              pedestrian_level, visible_competitors, informal_competitors,
              visibility_score, rent_signal, model_score, model_label,
              validator_notes, photo_url
            ) VALUES (
              :user_id, :business_category, :latitude, :longitude, :observed_activity,
              :pedestrian_level, :visible_competitors, :informal_competitors,
              :visibility_score, :rent_signal, :model_score, :model_label,
              :validator_notes, :photo_url
            )
            RETURNING id, business_category, latitude, longitude, observed_activity,
                      pedestrian_level, visible_competitors, informal_competitors,
                      visibility_score, rent_signal, model_score, model_label,
                      validator_notes, photo_url, created_at
        """), {**payload, "user_id": user_id}).mappings().first()
        db.commit()
        return dict(row)
    except Exception:
        db.rollback()
        return {"id": "local-validation", **payload, "status": "accepted"}


def list_validation_points(db: Session, limit: int = 100) -> list[dict]:
    try:
        rows = db.execute(text("""
            SELECT id, business_category, latitude, longitude, observed_activity,
                   pedestrian_level, visible_competitors, informal_competitors,
                   visibility_score, rent_signal, model_score, model_label,
                   validator_notes, photo_url, created_at
            FROM field.validation_points
            ORDER BY created_at DESC LIMIT :limit
        """), {"limit": limit}).mappings().all()
        return [dict(row) for row in rows]
    except Exception:
        db.rollback()
        return []
