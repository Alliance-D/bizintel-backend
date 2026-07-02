from sqlalchemy import text
from sqlalchemy.orm import Session


def build_weekly_digest_candidates(db: Session) -> list[dict]:
    rows = db.execute(text('''
        SELECT user_id, notification_frequency, default_business_category
        FROM app.user_preferences
        WHERE notification_frequency IN ('weekly', 'monthly')
    ''')).mappings().all()
    return [dict(row) for row in rows]
