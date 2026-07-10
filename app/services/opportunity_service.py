from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.location_labels import location_label


def _normalise_row(row: Any, locale: str | None = None) -> dict[str, Any]:
    data = dict(row)
    # Keep a stable contract for every frontend page.
    data.setdefault("name", data.get("grid_id", "Opportunity zone"))
    data.setdefault("zone_key", "emerging")
    data.setdefault("opportunity_type", data.get("experience_badge", "Worth comparing"))
    data.setdefault("risk_level", "medium")
    data["location_label"] = location_label(data.get("district"), data.get("sector"), data.get("cell"), data.get("village"), locale)
    return data


def list_opportunity_cells(
    db: Session, category: str = "salon", district: str | None = None,
    sector: str | None = None, cell: str | None = None, limit: int = 50, locale: str | None = None,
) -> list[dict[str, Any]]:
    """Return top opportunity cells, optionally scoped down to a sector or cell
    within a district (used for the "rank best cells in this area" flow).

    Uses real ML predictions only. Empty output means the backend data pipeline has not produced predictions yet.
    """
    try:
        sql = """
            SELECT
                p.grid_id,
                p.business_category,
                p.opportunity_score,
                p.opportunity_type,
                p.demand_score,
                p.accessibility_score,
                p.commercial_activity_score,
                p.competition_pressure,
                p.confidence_score,
                p.opportunity_rank,
                p.explanation,
                ST_Y(p.geom) AS latitude,
                ST_X(p.geom) AS longitude,
                COALESCE(NULLIF(p.district, ''), 'Kigali') AS district,
                p.sector,
                p.cell,
                g.village
            FROM ml.ml_opportunity_predictions p
            LEFT JOIN geo.analysis_grid g ON g.grid_id = p.grid_id
            WHERE p.business_category = :category
        """
        params: dict[str, Any] = {"category": category, "limit": limit}
        if district:
            sql += " AND lower(p.district) = lower(:district)"
            params["district"] = district
        if sector:
            sql += " AND lower(p.sector) = lower(:sector)"
            params["sector"] = sector
        if cell:
            sql += " AND lower(p.cell) = lower(:cell)"
            params["cell"] = cell
        sql += " ORDER BY p.opportunity_score DESC, p.confidence_score DESC LIMIT :limit"
        rows = db.execute(text(sql), params).mappings().all()
        if rows:
            return [_normalise_row(r, locale) for r in rows]
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
