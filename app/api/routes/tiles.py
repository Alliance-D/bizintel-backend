from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter()


@router.get('/opportunity/{z}/{x}/{y}.mvt')
def opportunity_tile(
    z: int,
    x: int,
    y: int,
    category: str = Query('salon'),
    db: Session = Depends(get_db),
) -> Response:
    """Serve vector tiles when SQL tile functions exist.

    Returning an empty MVT instead of a 500 keeps MapLibre stable while the real
    ML prediction tile cache is being generated.
    """
    try:
        tile = db.execute(
            text('SELECT ml.opportunity_tile(:z, :x, :y, :category)'),
            {'z': z, 'x': x, 'y': y, 'category': category},
        ).scalar()
        content = bytes(tile or b'')
    except Exception:
        db.rollback()
        content = b''
    return Response(content=content, media_type='application/vnd.mapbox-vector-tile')
