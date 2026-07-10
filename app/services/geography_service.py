"""Location-hierarchy lookups for the form's district/sector/cell picker.

Deliberately queries geo.analysis_grid (not geo.admin_boundaries) so the
picker only ever offers areas that actually have scored ML grid cells -
admin_boundaries covers all of Rwanda, but the model only covers Kigali's
three districts.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def list_districts(db: Session) -> list[str]:
    try:
        rows = db.execute(text("""
            SELECT DISTINCT district FROM geo.analysis_grid
            WHERE district IS NOT NULL ORDER BY district
        """)).scalars().all()
        return list(rows)
    except Exception:
        db.rollback()
        return []


def list_sectors(db: Session, district: str) -> list[str]:
    try:
        rows = db.execute(text("""
            SELECT DISTINCT sector FROM geo.analysis_grid
            WHERE lower(district) = lower(:district) AND sector IS NOT NULL
            ORDER BY sector
        """), {"district": district}).scalars().all()
        return list(rows)
    except Exception:
        db.rollback()
        return []


def list_cells(db: Session, district: str, sector: str) -> list[str]:
    try:
        rows = db.execute(text("""
            SELECT DISTINCT cell FROM geo.analysis_grid
            WHERE lower(district) = lower(:district) AND lower(sector) = lower(:sector) AND cell IS NOT NULL
            ORDER BY cell
        """), {"district": district, "sector": sector}).scalars().all()
        return list(rows)
    except Exception:
        db.rollback()
        return []


def get_village_boundary(db: Session, latitude: float, longitude: float) -> dict[str, Any] | None:
    try:
        row = db.execute(text("""
            SELECT province, district, sector, cell, village, ST_AsGeoJSON(geom) AS geometry
            FROM geo.admin_boundaries
            WHERE boundary_level = 'village' AND geom IS NOT NULL
              AND ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
            LIMIT 1
        """), {"lon": longitude, "lat": latitude}).mappings().first()
        return dict(row) if row else None
    except Exception:
        db.rollback()
        return None
