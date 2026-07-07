from sqlalchemy import text
from sqlalchemy.orm import Session


def create_saved_location(db: Session, payload: dict) -> dict:
    row = db.execute(text("""
        INSERT INTO app.saved_locations (label, business_category, latitude, longitude, geom, notes, updated_at)
        VALUES (:label, :category, :lat, :lon, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :notes, now())
        RETURNING id, label, business_category, latitude, longitude, notes, created_at, updated_at
    """), {
        'label': payload['label'],
        'category': payload['business_category'],
        'lat': payload['latitude'],
        'lon': payload['longitude'],
        'notes': payload.get('notes'),
    }).mappings().first()
    db.commit()
    return dict(row) if row else payload


def list_saved_locations(db: Session, limit: int = 50) -> list[dict]:
    try:
        rows = db.execute(text("SELECT * FROM app.saved_location_summary ORDER BY created_at DESC LIMIT :limit"), {'limit': limit}).mappings().all()
        return [dict(r) for r in rows]
    except Exception:
        db.rollback()
        return []


def list_alerts(db: Session, limit: int = 30) -> list[dict]:
    try:
        rows = db.execute(text("""
            SELECT id, alert_type, severity, title, message, is_read, created_at, saved_location_id
            FROM app.alerts
            WHERE saved_location_id IS NOT NULL
            ORDER BY created_at DESC
            LIMIT :limit
        """), {'limit': limit}).mappings().all()
        return [dict(r) for r in rows]
    except Exception:
        db.rollback()
        return []


def delete_saved_location(db: Session, location_id: int) -> dict | None:
    existing = db.execute(text("""
        SELECT id, label, business_category, latitude, longitude
        FROM app.saved_locations
        WHERE id = :id
    """), {'id': location_id}).mappings().first()
    if not existing:
        return None

    db.execute(text("DELETE FROM app.alerts WHERE saved_location_id = :id"), {'id': location_id})
    db.execute(text("UPDATE app.location_reports SET saved_location_id = NULL WHERE saved_location_id = :id"), {'id': location_id})
    db.execute(text("DELETE FROM app.saved_locations WHERE id = :id"), {'id': location_id})
    db.commit()
    return dict(existing)
