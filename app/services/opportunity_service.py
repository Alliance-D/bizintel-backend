from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def _normalise_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    # Keep a stable contract for every frontend page.
    data.setdefault("name", data.get("grid_id", "Opportunity zone"))
    data.setdefault("zone_key", "emerging")
    data.setdefault("opportunity_type", data.get("experience_badge", "Worth comparing"))
    data.setdefault("risk_level", "medium")
    return data


def list_opportunity_cells(db: Session, category: str = "salon", district: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """Return top opportunity cells.

    Uses real ML predictions only. Empty output means the backend data pipeline has not produced predictions yet.
    """
    try:
        sql = """
            SELECT
                grid_id,
                business_category,
                opportunity_score,
                opportunity_type,
                demand_score,
                accessibility_score,
                commercial_activity_score,
                competition_pressure,
                confidence_score,
                opportunity_rank,
                explanation,
                ST_Y(geom) AS latitude,
                ST_X(geom) AS longitude,
                COALESCE(NULLIF(district, ''), 'Kigali') AS district
            FROM ml.ml_opportunity_predictions
            WHERE business_category = :category
        """
        params: dict[str, Any] = {"category": category, "limit": limit}
        if district:
            sql += " AND lower(district) = lower(:district)"
            params["district"] = district
        sql += " ORDER BY opportunity_score DESC, confidence_score DESC LIMIT :limit"
        rows = db.execute(text(sql), params).mappings().all()
        if rows:
            return [_normalise_row(r) for r in rows]
    except Exception:
        db.rollback()
    return []


def summarize_opportunity_map(cells: list[dict[str, Any]]) -> dict[str, Any]:
    zone_counts = Counter(c.get("zone_key") or c.get("opportunity_type") or "emerging" for c in cells)
    if not cells:
        return {
            "total_cells": 0,
            "average_opportunity": 0,
            "average_demand": 0,
            "average_access": 0,
            "average_competition": 0,
            "zone_counts": {},
        }
    def avg(key: str) -> float:
        return round(sum(float(c.get(key) or 0) for c in cells) / len(cells), 2)
    return {
        "total_cells": len(cells),
        "average_opportunity": avg("opportunity_score"),
        "average_demand": avg("demand_score"),
        "average_access": avg("accessibility_score"),
        "average_competition": avg("competition_pressure"),
        "average_confidence": avg("confidence_score"),
        "zone_counts": dict(zone_counts),
        "best_zone": max(cells, key=lambda c: c.get("opportunity_score") or 0) if cells else None,
    }
