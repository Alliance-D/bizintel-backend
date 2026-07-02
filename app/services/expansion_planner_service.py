"""Expansion Planner: given one or more existing/candidate locations for a
business category, rank other high-opportunity zones for a next branch -
reusing the same real opportunity predictions Scout and the Opportunity Map
already use, not a separate model.

Two rules keep the results genuinely useful for expansion (not just "the
top N opportunity cells regardless of where they are"):
  1. Exclude cells too close to an existing location (no point suggesting a
     spot that would cannibalize the same catchment).
  2. Spread the returned candidates apart from each other, so the list
     covers different areas instead of clustering around one opportunity peak.
"""
from __future__ import annotations

import math
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

DEFAULT_MIN_DISTANCE_FROM_EXISTING_M = 600
DEFAULT_MIN_SPACING_BETWEEN_CANDIDATES_M = 400


def meters_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Equirectangular approximation - good enough at Kigali's scale (a few km) and avoids a DB round-trip per pair."""
    r = 6371000
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return math.sqrt(x * x + y * y) * r


def plan_expansion(
    db: Session,
    business_category: str,
    existing_locations: list[dict[str, float]],
    limit: int = 8,
    min_distance_from_existing_m: int = DEFAULT_MIN_DISTANCE_FROM_EXISTING_M,
) -> dict[str, Any]:
    try:
        candidates = db.execute(text("""
            SELECT grid_id, opportunity_score, demand_score, accessibility_score,
                   commercial_activity_score, competition_pressure, confidence_score,
                   opportunity_type, risk_level, district, sector,
                   ST_Y(geom) AS latitude, ST_X(geom) AS longitude, geom
            FROM ml.ml_opportunity_predictions
            WHERE business_category = :category
            ORDER BY opportunity_score DESC, confidence_score DESC
            LIMIT 400
        """), {"category": business_category}).mappings().all()
    except Exception:
        db.rollback()
        return {"business_category": business_category, "candidates": [], "excluded_near_existing": 0}

    if not candidates:
        return {"business_category": business_category, "candidates": [], "excluded_near_existing": 0}

    existing_points = [(loc["latitude"], loc["longitude"]) for loc in existing_locations if "latitude" in loc and "longitude" in loc]

    excluded_near_existing = 0
    filtered = []
    for row in candidates:
        too_close_to_existing = any(
            meters_between(row["latitude"], row["longitude"], lat, lon) < min_distance_from_existing_m
            for lat, lon in existing_points
        )
        if too_close_to_existing:
            excluded_near_existing += 1
            continue
        filtered.append(row)

    selected: list[dict[str, Any]] = []
    for row in filtered:
        if len(selected) >= limit:
            break
        too_close_to_selected = any(
            meters_between(row["latitude"], row["longitude"], s["latitude"], s["longitude"]) < DEFAULT_MIN_SPACING_BETWEEN_CANDIDATES_M
            for s in selected
        )
        if too_close_to_selected:
            continue
        selected.append({
            "grid_id": row["grid_id"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "opportunity_score": round(float(row["opportunity_score"]), 2),
            "demand_score": round(float(row["demand_score"] or 0), 2),
            "accessibility_score": round(float(row["accessibility_score"] or 0), 2),
            "commercial_activity_score": round(float(row["commercial_activity_score"] or 0), 2),
            "competition_pressure": round(float(row["competition_pressure"] or 0), 2),
            "confidence_score": round(float(row["confidence_score"] or 0), 2),
            "opportunity_type": row["opportunity_type"],
            "risk_level": row["risk_level"],
            "district": row["district"],
            "sector": row["sector"],
            "distance_from_nearest_existing_m": round(
                min((meters_between(row["latitude"], row["longitude"], lat, lon) for lat, lon in existing_points), default=0), 1
            ) if existing_points else None,
        })

    return {
        "business_category": business_category,
        "existing_location_count": len(existing_points),
        "candidates": selected,
        "excluded_near_existing": excluded_near_existing,
        "min_distance_from_existing_m": min_distance_from_existing_m,
    }
