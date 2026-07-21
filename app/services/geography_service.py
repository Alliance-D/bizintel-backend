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
    """List the distinct districts present in the analysis grid."""
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
    """List the sectors within a district."""
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
    """List the cells within a district and sector."""
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


def nearest_landmark(db: Session, latitude: float, longitude: float, locale: str | None = None) -> str | None:
    """A recognisable place near a point - the closest named market, school,
    health facility, bus hub, bank or notable business within ~800m - so two
    grid cells inside the same administrative cell can be told apart by
    something a person can actually picture ("Kimironko market"), rather than
    sharing an identical cell label. Returns the bare place name (the "near"/
    "hafi ya" connector is added by the client so it translates); returns None
    if nothing recognisable is close, and callers fall back to the cell name.
    The locale arg is accepted for signature compatibility but no longer used -
    a proper place name is the same in either language.
    """
    try:
        # Geometry KNN (<->) + a bbox ST_DWithin both use the GiST index on
        # geom, so this is a fast index lookup rather than a per-row scan with
        # the geography cast. ~0.0075 deg is roughly 800 m at Kigali's latitude;
        # the exact radius is a heuristic for "a recognisable place nearby".
        row = db.execute(text("""
            SELECT name
            FROM curated.osm_poi_features
            WHERE name IS NOT NULL AND btrim(name) <> ''
              AND category_key IN ('market','transport','health','school','finance','commercial_support')
              AND ST_DWithin(geom, ST_SetSRID(ST_MakePoint(:lon,:lat),4326), 0.0075)
            ORDER BY geom <-> ST_SetSRID(ST_MakePoint(:lon,:lat),4326)
            LIMIT 1
        """), {"lon": longitude, "lat": latitude}).mappings().first()
        if row and row["name"]:
            return str(row["name"]).strip()
    except Exception:
        db.rollback()
    return None


def get_village_boundary(db: Session, latitude: float, longitude: float) -> dict[str, Any] | None:
    """Return the administrative area and its boundary polygon at a point."""
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
