from fastapi import APIRouter
from sqlalchemy import text
from app.db.session import engine

router = APIRouter()


@router.get("/health")
def health() -> dict:
    """Liveness probe: reports healthy when the database is reachable, degraded otherwise."""
    db_ok = False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            db_ok = True
    except Exception:
        db_ok = False
    return {"status": "healthy" if db_ok else "degraded", "database": db_ok}
