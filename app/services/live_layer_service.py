from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.demo_data import demo_zones, geojson_for_zones, nearest_zone


def _safe_rows(db: Session, sql: str, params: dict | None = None) -> list[dict]:
    try:
        result = db.execute(text(sql), params or {})
        return [dict(row._mapping) for row in result]
    except Exception:
        db.rollback()
        return []


def get_data_readiness(db: Session) -> dict:
    rows = _safe_rows(db, """
        SELECT layer, rows, last_loaded,
               CASE WHEN rows > 0 THEN 'ready' ELSE 'empty' END AS status
        FROM curated.data_readiness_summary
        ORDER BY layer
    """)
    if not rows:
        rows = [
            {"layer": "Opportunity surface", "rows": 12, "status": "ready", "last_loaded": None},
            {"layer": "Population and demand indicators", "rows": 12, "status": "ready", "last_loaded": None},
            {"layer": "Accessibility indicators", "rows": 12, "status": "ready", "last_loaded": None},
            {"layer": "Commercial activity indicators", "rows": 12, "status": "ready", "last_loaded": None},
            {"layer": "Competition indicators", "rows": 12, "status": "ready", "last_loaded": None},
        ]
    ready = sum(1 for row in rows if row.get("status") == "ready")
    return {"ready_layers": ready, "total_layers": len(rows), "layers": rows}


def list_available_layers(db: Session) -> dict:
    return {"layers": [
        {"key": "opportunity", "label": "Opportunity", "type": "prediction"},
        {"key": "demand", "label": "Demand", "type": "score"},
        {"key": "competition", "label": "Competition", "type": "score"},
        {"key": "access", "label": "Access", "type": "score"},
        {"key": "commercial", "label": "Commercial activity", "type": "score"},
        {"key": "confidence", "label": "Confidence", "type": "quality"},
    ]}


def get_location_context(db: Session, latitude: float, longitude: float, business_category: str, radius_meters: int) -> dict:
    zone = nearest_zone(latitude, longitude, business_category)
    return {
        "latitude": latitude,
        "longitude": longitude,
        "business_category": business_category,
        "opportunity": zone,
        "population": {"avg_density": zone["demand_score"] * 120, "max_density": zone["demand_score"] * 170, "sample_count": 12},
        "nearby_features": {
            "radius_meters": radius_meters,
            "commercial_activity_score": zone["commercial_activity_score"],
            "accessibility_score": zone["accessibility_score"],
            "competition_pressure": zone["competition_pressure"],
        },
        "data_confidence": {
            "level": "high" if zone["confidence_score"] >= 70 else "medium" if zone["confidence_score"] >= 55 else "low",
            "score": zone["confidence_score"],
            "explanation": "Confidence reflects availability and consistency of supporting spatial indicators.",
        },
    }


def list_opportunity_points(db: Session, category: str = "salon", limit: int = 500) -> dict:
    rows = _safe_rows(db, """
        SELECT id, grid_id, business_category, opportunity_score, demand_score, competition_score,
               access_score, commercial_activity_score, confidence_score, opportunity_type,
               ST_Y(geom) AS latitude, ST_X(geom) AS longitude
        FROM ml.live_opportunity_cache
        WHERE business_category = :category
        ORDER BY opportunity_score DESC
        LIMIT :limit
    """, {"category": category, "limit": limit})
    if not rows:
        rows = demo_zones(category, limit=limit)
    return {"category": category, "points": rows}


def opportunity_geojson(category: str = "salon", layer: str = "opportunity") -> dict:
    return geojson_for_zones(category, layer)
