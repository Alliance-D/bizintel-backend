from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.services.notification_service import list_notifications, upsert_preferences

router = APIRouter()

class NotificationPreferences(BaseModel):
    weekly_digest: bool = True
    opportunity_alerts: bool = True
    competition_alerts: bool = True
    email_enabled: bool = False

@router.get('/notifications')
def notifications(limit: int = Query(30, ge=1, le=100), db: Session = Depends(get_db)) -> dict:
    return {'notifications': list_notifications(db, limit=limit)}

@router.put('/notification-preferences')
def notification_preferences(payload: NotificationPreferences, db: Session = Depends(get_db)) -> dict:
    return {'preferences': upsert_preferences(db, user_id=1, payload=payload.model_dump())}
