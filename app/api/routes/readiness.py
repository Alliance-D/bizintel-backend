from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.final import ReadinessResponse
from app.services.readiness_service import get_readiness

router = APIRouter()


@router.get("", response_model=ReadinessResponse)
def readiness(db: Session = Depends(get_db)) -> dict:
    """Launch/demo readiness endpoint."""
    return get_readiness(db)
