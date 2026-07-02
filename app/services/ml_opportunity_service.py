from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session



def list_category_profiles(db: Session) -> dict[str, Any]:
    try:
        rows = db.execute(text("""
            SELECT category_key, display_name, description, demand_weight, access_weight,
                   commercial_weight, competition_weight, welfare_weight,
                   min_confidence_threshold, is_active
            FROM curated.business_category_profiles
            WHERE is_active = TRUE
            ORDER BY display_name
        """)).mappings().all()
        if rows:
            return {"categories": [{
                "category_key": r["category_key"],
                "display_name": r["display_name"],
                "description": r["description"],
                "weights": {
                    "demand": float(r["demand_weight"] or 0),
                    "access": float(r["access_weight"] or 0),
                    "commercial": float(r["commercial_weight"] or 0),
                    "competition": float(r["competition_weight"] or 0),
                    "welfare": float(r["welfare_weight"] or 0),
                },
                "confidence_threshold": r["min_confidence_threshold"],
            } for r in rows]}
    except Exception:
        db.rollback()
    return {"categories": [], "source": "database_unavailable"}


def assess_location_ml(db: Session, latitude: float, longitude: float, business_category: str, radius_meters: int = 500) -> dict[str, Any]:
    try:
        prediction = db.execute(text("SELECT * FROM ml.get_ml_prediction_near(:lon, :lat, :category)"), {
            "lon": longitude, "lat": latitude, "category": business_category
        }).mappings().first()
        if prediction:
            competitors = _competitors(db, longitude, latitude, business_category, radius_meters)
            return _prediction_payload(dict(prediction), latitude, longitude, business_category, competitors)
    except Exception:
        db.rollback()

    return {
        "status": "unavailable",
        "source": "no_ml_prediction_cache",
        "business_category": business_category,
        "latitude": latitude,
        "longitude": longitude,
        "overall": {"opportunity_score": 0, "confidence_score": 0, "opportunity_type": "Prediction unavailable", "opportunity_rank": None},
        "factors": {"demand_score": 0, "accessibility_score": 0, "commercial_activity_score": 0, "competition_pressure": 0},
        "competition": {"within_300m": 0, "within_500m": 0, "within_1000m": 0},
        "nearby_context": [],
        "explanation": {"summary": "No prediction was found for this location and category."},
        "risk_notes": ["Live prediction data is unavailable."],
        "recommendation": "Refresh the map or try another nearby location.",
    }


def _competitors(db: Session, longitude: float, latitude: float, category: str, radius_meters: int) -> dict[str, int]:
    try:
        row = db.execute(text("""
            SELECT
              COUNT(*) FILTER (WHERE ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography, 300)) AS within_300m,
              COUNT(*) FILTER (WHERE ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography, 500)) AS within_500m,
              COUNT(*) FILTER (WHERE ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography, 1000)) AS within_1000m
            FROM curated.osm_poi_features
            WHERE category_key = :category
        """), {"lon": longitude, "lat": latitude, "category": category, "radius": radius_meters}).mappings().first()
        if row:
            return {"within_300m": int(row["within_300m"] or 0), "within_500m": int(row["within_500m"] or 0), "within_1000m": int(row["within_1000m"] or 0)}
    except Exception:
        db.rollback()
    return {"within_300m": 0, "within_500m": 0, "within_1000m": 0}


def _prediction_payload(prediction: dict[str, Any], latitude: float, longitude: float, category: str, competitors: dict[str, int], source: str = "ml_prediction_cache") -> dict[str, Any]:
    score = round(float(prediction.get("opportunity_score") or 0), 2)
    confidence = round(float(prediction.get("confidence_score") or 0), 2)
    competition = round(float(prediction.get("competition_pressure") or 0), 2)
    access = round(float(prediction.get("accessibility_score") or prediction.get("access_score") or 0), 2)
    commercial = round(float(prediction.get("commercial_activity_score") or 0), 2)
    demand = round(float(prediction.get("demand_score") or 0), 2)
    return {
        "status": "ready",
        "source": source,
        "business_category": category,
        "latitude": latitude,
        "longitude": longitude,
        "nearest_grid_id": prediction.get("grid_id"),
        "distance_to_grid_m": prediction.get("distance_m") or prediction.get("distance_to_grid_m"),
        "model_version_id": prediction.get("model_version_id"),
        "overall": {
            "opportunity_score": score,
            "opportunity_rank": prediction.get("opportunity_rank"),
            "opportunity_type": prediction.get("opportunity_type", "Worth comparing"),
            "confidence_score": confidence,
        },
        "factors": {
            "demand_score": demand,
            "accessibility_score": access,
            "commercial_activity_score": commercial,
            "competition_pressure": competition,
        },
        "competition": competitors,
        "nearby_context": [],
        "explanation": prediction.get("explanation") or {},
        "risk_notes": _risk_notes(score, competition, confidence, access),
        "recommendation": _recommendation(score, confidence, competition),
    }


def list_top_opportunity_zones(db: Session, business_category: str, limit: int = 25) -> dict[str, Any]:
    try:
        rows = db.execute(text("""
            SELECT grid_id, business_category, opportunity_score, opportunity_rank, opportunity_type,
                   confidence_score, ST_Y(geom) AS latitude, ST_X(geom) AS longitude, explanation
            FROM ml.ml_opportunity_predictions
            WHERE business_category = :category
            ORDER BY opportunity_score DESC, confidence_score DESC
            LIMIT :limit
        """), {"category": business_category, "limit": limit}).mappings().all()
        if rows:
            return {"business_category": business_category, "zones": [dict(r) for r in rows]}
    except Exception:
        db.rollback()
    return {"business_category": business_category, "zones": [], "source": "database_unavailable"}


def get_ml_engine_status(db: Session) -> dict[str, Any]:
    try:
        counts = db.execute(text("""
            SELECT
              (SELECT COUNT(*) FROM curated.osm_poi_features) AS osm_pois,
              (SELECT COUNT(*) FROM ml.grid_category_features) AS grid_features,
              (SELECT COUNT(*) FROM ml.ml_opportunity_predictions) AS predictions,
              (SELECT COUNT(*) FROM curated.business_category_profiles WHERE is_active = TRUE) AS active_categories
        """)).mappings().first()
        by_category = db.execute(text("""
            SELECT business_category, COUNT(*) AS prediction_rows, AVG(opportunity_score) AS avg_score, MAX(opportunity_score) AS max_score
            FROM ml.ml_opportunity_predictions
            GROUP BY business_category ORDER BY business_category
        """)).mappings().all()
        return {"mode": "ml_cache", "readiness": dict(counts or {}), "prediction_summary_by_category": [dict(r) for r in by_category]}
    except Exception:
        db.rollback()
        return {
            "mode": "unavailable",
            "readiness": {"osm_pois": 0, "grid_features": 0, "predictions": 0, "active_categories": 0},
            "prediction_summary_by_category": [],
            "message": "Prediction tables are unavailable.",
        }


def _risk_notes(score: float, competition: float, confidence: float, access: float) -> list[str]:
    notes = []
    if competition >= 70:
        notes.append("Competition pressure is high near this location.")
    if confidence < 55:
        notes.append("Data confidence is moderate; validate informal competitors and customer flow.")
    if access < 45:
        notes.append("Accessibility is weaker than stronger opportunity zones.")
    if score < 50:
        notes.append("The area should be compared with stronger nearby alternatives before committing.")
    return notes


def _recommendation(score: float, confidence: float, competition_pressure: float) -> str:
    if confidence < 45:
        return "Use this as an exploratory signal and validate the area physically before making decisions."
    if score >= 80 and competition_pressure < 60:
        return "Strong candidate area. Prioritize field checks for rent, frontage and informal competitors."
    if score >= 65 and competition_pressure >= 70:
        return "Promising but competitive. Consider differentiation rather than a generic offer."
    if score >= 50:
        return "Moderate opportunity. Compare this location with nearby alternatives before committing."
    return "Weak opportunity under current model signals. Look for stronger demand, access or commercial activity nearby."
