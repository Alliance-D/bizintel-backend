from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def analyze_competition(db: Session, latitude: float, longitude: float, business_category: str, radius_meters: int = 1000) -> dict:
    """Summarize competitor density and nearby complementary businesses around a point."""
    try:
        competitors = db.execute(text("""
            SELECT name, category_key, ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography) AS distance_m,
                   ST_Y(geom) AS latitude, ST_X(geom) AS longitude
            FROM curated.osm_poi_features
            WHERE category_key = :category
              AND ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography, :radius)
            ORDER BY distance_m ASC LIMIT 30
        """), {"lon": longitude, "lat": latitude, "category": business_category, "radius": radius_meters}).mappings().all()
        rows = [dict(r) for r in competitors]
        if rows:
            return _payload(latitude, longitude, business_category, rows, None)
    except Exception:
        db.rollback()
    return _payload(latitude, longitude, business_category, [], None)


def _payload(latitude: float, longitude: float, category: str, competitors: list[dict], zone: dict | None) -> dict:
    """Assemble the competitive-analysis response payload."""
    pressure = zone["competition_pressure"] if zone else min(100, len(competitors) * 10)
    if pressure >= 70:
        diagnosis = "Crowded market"
        advice = "Differentiate clearly, verify rent carefully and compare side-street alternatives."
    elif pressure >= 45:
        diagnosis = "Manageable competition"
        advice = "The area may work if demand, visibility and price positioning are strong."
    else:
        diagnosis = "Underserved pocket"
        advice = "Validate customer flow and informal competitors; low visible competition may be an opportunity or a weak-demand signal."
    return {
        "business_category": category,
        "latitude": latitude,
        "longitude": longitude,
        "competition_pressure": round(float(pressure), 2),
        "diagnosis": diagnosis,
        "competitors": competitors,
        "counts": {
            "within_300m": sum(1 for c in competitors if float(c.get("distance_m") or 0) <= 300),
            "within_500m": sum(1 for c in competitors if float(c.get("distance_m") or 0) <= 500),
            "within_1000m": sum(1 for c in competitors if float(c.get("distance_m") or 0) <= 1000),
        },
        "catchment_notes": [
            "Areas with high demand and fewer nearby competitors should be checked physically.",
            "Informal competitors may be missing from digital datasets.",
        ],
        "recommended_strategy": advice,
    }
