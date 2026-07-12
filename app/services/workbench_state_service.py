import json
from sqlalchemy import text
from sqlalchemy.orm import Session


def _json(value):
    """JSON-encode a value for storage in a JSONB column."""
    return json.dumps(value if value is not None else {})


def list_workbench_states(db: Session, user_id: int) -> list[dict]:
    """List a user's saved workbench states."""
    rows = db.execute(text('''
        SELECT id, title, description, business_category, center_lat, center_lon,
               zoom_level, active_layers, filters, selected_locations, state_payload,
               is_pinned, created_at, updated_at
        FROM app.saved_workbench_states
        WHERE user_id = :user_id
        ORDER BY is_pinned DESC, updated_at DESC
    '''), {'user_id': user_id}).mappings().all()
    return [dict(row) for row in rows]


def create_workbench_state(db: Session, user_id: int, payload: dict) -> dict:
    """Persist a workbench state for a user."""
    row = db.execute(text('''
        INSERT INTO app.saved_workbench_states (
            user_id, title, description, business_category, center_lat, center_lon,
            zoom_level, active_layers, filters, selected_locations, state_payload, is_pinned
        ) VALUES (
            :user_id, :title, :description, :business_category, :center_lat, :center_lon,
            :zoom_level, :active_layers, CAST(:filters AS jsonb), CAST(:selected_locations AS jsonb),
            CAST(:state_payload AS jsonb), :is_pinned
        )
        RETURNING *
    '''), {
        'user_id': user_id,
        'title': payload['title'],
        'description': payload.get('description'),
        'business_category': payload.get('business_category', 'salon'),
        'center_lat': payload.get('center_lat'),
        'center_lon': payload.get('center_lon'),
        'zoom_level': payload.get('zoom_level', 12),
        'active_layers': payload.get('active_layers', ['opportunity']),
        'filters': _json(payload.get('filters', {})),
        'selected_locations': _json(payload.get('selected_locations', [])),
        'state_payload': _json(payload.get('state_payload', {})),
        'is_pinned': payload.get('is_pinned', False),
    }).mappings().first()
    db.commit()
    return dict(row)


def delete_workbench_state(db: Session, user_id: int, state_id: int) -> bool:
    """Delete a user's workbench state, returning whether a row was removed."""
    result = db.execute(text('DELETE FROM app.saved_workbench_states WHERE id = :id AND user_id = :user_id'), {'id': state_id, 'user_id': user_id})
    db.commit()
    return result.rowcount > 0


def get_or_create_preferences(db: Session, user_id: int) -> dict:
    """Return a user's preferences, creating defaults if none exist."""
    row = db.execute(text('''
        INSERT INTO app.user_preferences (user_id)
        VALUES (:user_id)
        ON CONFLICT (user_id) DO UPDATE SET user_id = EXCLUDED.user_id
        RETURNING *
    '''), {'user_id': user_id}).mappings().first()
    db.commit()
    return dict(row)


def update_preferences(db: Session, user_id: int, payload: dict) -> dict:
    """Update a user's preferences and return them."""
    current = get_or_create_preferences(db, user_id)
    merged = {**current, **{k: v for k, v in payload.items() if v is not None}}
    row = db.execute(text('''
        UPDATE app.user_preferences
        SET default_business_category = :default_business_category,
            default_radius_meters = :default_radius_meters,
            theme = :theme,
            map_style = :map_style,
            notification_frequency = :notification_frequency,
            preferred_districts = :preferred_districts,
            preferred_budget_level = :preferred_budget_level
        WHERE user_id = :user_id
        RETURNING *
    '''), {
        'user_id': user_id,
        'default_business_category': merged.get('default_business_category', 'salon'),
        'default_radius_meters': merged.get('default_radius_meters', 500),
        'theme': merged.get('theme', 'light'),
        'map_style': merged.get('map_style', 'standard'),
        'notification_frequency': merged.get('notification_frequency', 'weekly'),
        'preferred_districts': merged.get('preferred_districts', []),
        'preferred_budget_level': merged.get('preferred_budget_level'),
    }).mappings().first()
    db.commit()
    return dict(row)
