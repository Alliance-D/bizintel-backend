from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def list_datasets(db: Session, limit: int = 200) -> list[dict]:
    try:
        rows = db.execute(text("""
            SELECT dataset_key, title, owner, license_status, permission_status,
                   recommended_layer, relevance, rows_estimate, columns_count, size_mb, imported_at, notes
            FROM meta.dataset_catalog
            ORDER BY size_mb DESC NULLS LAST, title
            LIMIT :limit
        """), {"limit": limit}).mappings().all()
        return [dict(r) for r in rows]
    except Exception:
        return []


def list_features(db: Session, limit: int = 300) -> list[dict]:
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
    checks = {}
    for key, query in {
        "population_density_points": "SELECT COUNT(*) FROM geo.population_density_grid",
        "analysis_grid_cells": "SELECT COUNT(*) FROM geo.analysis_grid",
        "osm_pois": "SELECT COUNT(*) FROM geo.osm_pois",
        "osm_roads": "SELECT COUNT(*) FROM geo.osm_roads",
        "training_feature_rows": "SELECT COUNT(*) FROM ml.training_features",
        "dataset_catalog_rows": "SELECT COUNT(*) FROM meta.dataset_catalog",
    }.items():
        try:
            checks[key] = db.execute(text(query)).scalar_one()
        except Exception:
            checks[key] = None
    ready_for_training = bool(
        (checks.get("analysis_grid_cells") or 0) > 0
        and (checks.get("training_feature_rows") or 0) > 0
    )
    return {"checks": checks, "ready_for_training": ready_for_training}
