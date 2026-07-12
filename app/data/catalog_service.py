from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def list_datasets(db: Session, limit: int = 200) -> list[dict]:
    """Real import history from raw.dataset_imports, written by each import script."""
    try:
        rows = db.execute(text("""
            SELECT dataset_key, source_path, source_owner, license_status, permission_status,
                   rows_imported, import_status, message, started_at, finished_at
            FROM raw.dataset_imports
            ORDER BY finished_at DESC NULLS LAST, started_at DESC
            LIMIT :limit
        """), {"limit": limit}).mappings().all()
        return [dict(r) for r in rows]
    except Exception:
        return []


def list_features(db: Session, limit: int = 300) -> list[dict]:
    """List engineered feature metadata from the feature catalog."""
    try:
        rows = db.execute(text("""
            SELECT feature_name, feature_group, source_layer, geographic_level,
                   business_category_specific, used_for_training, used_for_prediction,
                   calculation_method, interpretation, quality_risk
            FROM meta.feature_catalog
            ORDER BY feature_group, feature_name
            LIMIT :limit
        """), {"limit": limit}).mappings().all()
        return [dict(r) for r in rows]
    except Exception:
        return []


def data_health(db: Session) -> dict:
    """Return per-table row counts and pipeline-readiness flags."""
    checks = {}
    for key, query in {
        "population_density_points": "SELECT COUNT(*) FROM curated.population_density_points",
        "analysis_grid_cells": "SELECT COUNT(*) FROM geo.analysis_grid",
        "osm_pois": "SELECT COUNT(*) FROM curated.osm_poi_features",
        "establishment_area_rows": "SELECT COUNT(*) FROM curated.establishment_area_features",
        "population_welfare_rows": "SELECT COUNT(*) FROM curated.population_welfare_features",
        "grid_category_feature_rows": "SELECT COUNT(*) FROM ml.grid_category_features",
        "ml_predictions": "SELECT COUNT(*) FROM ml.ml_opportunity_predictions",
        "active_model_versions": "SELECT COUNT(*) FROM ml.model_versions WHERE is_active",
    }.items():
        try:
            checks[key] = db.execute(text(query)).scalar_one()
        except Exception:
            checks[key] = None
    ready_for_training = bool(
        (checks.get("analysis_grid_cells") or 0) > 0
        and (checks.get("grid_category_feature_rows") or 0) > 0
    )
    return {"checks": checks, "ready_for_training": ready_for_training}
