from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.location_labels import location_label
from app.services.geography_service import nearest_landmark


def _normalise_row(row: Any, locale: str | None = None) -> dict[str, Any]:
    """Normalize a raw opportunity-cell DB row into the API shape, localized."""
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
    with_landmarks: bool = False,
) -> list[dict[str, Any]]:
    """Return top opportunity cells, optionally scoped down to a sector or cell
    within a district (used for the "rank best cells in this area" flow).

    Uses real ML predictions only. Empty output means the backend data pipeline has not produced predictions yet.
    """
    try:
        # Exclude cells the map-quality screen flagged as water (a lake/wetland
        # cell must never surface as a "strongest spot"), mirroring the citywide
        # map. Guarded so the query still works where the screen isn't set up.
        try:
            has_quality = bool(db.execute(text("SELECT to_regclass('ml.map_quality_flags') IS NOT NULL")).scalar())
        except Exception:
            db.rollback()
            has_quality = False
        quality_join = "LEFT JOIN ml.map_quality_flags q ON q.grid_id = p.grid_id" if has_quality else ""
        quality_filter = "AND COALESCE(q.candidate_status, 'candidate') <> 'excluded_water'" if has_quality else ""
        sql = f"""
            SELECT
                p.grid_id,
                p.business_category,
                p.opportunity_score,
                p.opportunity_type,
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
            {quality_join}
            WHERE p.business_category = :category
            {quality_filter}
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
        sql += " ORDER BY p.opportunity_score DESC, p.opportunity_rank ASC LIMIT :limit"
        rows = db.execute(text(sql), params).mappings().all()
        if rows:
            out = [_normalise_row(r, locale) for r in rows]
            if with_landmarks:
                # only for the report's short candidate list (limit ~3) - one
                # extra query per row, not worth it for the citywide map.
                for row in out:
                    row["landmark"] = nearest_landmark(db, row.get("latitude"), row.get("longitude"), locale)
            return out
    except Exception:
        db.rollback()
    return []


def summarize_opportunity_map(cells: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize a set of cells: total count, zone counts and factor averages."""
    zone_counts = Counter(c.get("zone_key") or c.get("opportunity_type") or "emerging" for c in cells)
    if not cells:
        return {
            "total_cells": 0,
            "average_opportunity": 0,
            "zone_counts": {},
        }
    def avg(key: str) -> float:
        """Mean of a numeric field across the cells (0 when empty)."""
        return round(sum(float(c.get(key) or 0) for c in cells) / len(cells), 2)
    return {
        "total_cells": len(cells),
        "average_opportunity": avg("opportunity_score"),
        "zone_counts": dict(zone_counts),
        "best_zone": max(cells, key=lambda c: c.get("opportunity_score") or 0) if cells else None,
    }
