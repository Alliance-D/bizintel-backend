from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
from sqlalchemy import text
from sqlalchemy.orm import Session


def _artifact_root() -> Path:
    return Path(os.getenv("MODEL_ARTIFACT_DIR", "ml/artifacts")).expanduser().resolve()


def model_status(db: Session) -> dict[str, Any]:
    """Return registry status and active model metadata."""
    try:
        total = db.execute(text("SELECT COUNT(*) FROM ml.model_versions")).scalar_one()
        active = db.execute(text("""
            SELECT id, model_name, algorithm, target_name, business_category,
                   artifact_path, metrics, is_active, created_at, activated_at
            FROM ml.model_versions
            WHERE is_active = TRUE
            ORDER BY activated_at DESC NULLS LAST, created_at DESC
            LIMIT 1
        """)).mappings().first()
    except Exception as exc:
        return {
            "registry_ready": False,
            "model_count": 0,
            "active_model": None,
            "message": f"Model registry not ready: {exc.__class__.__name__}",
        }

    active_model = None
    if active:
        active_model = dict(active)
        best_metrics = (active_model.get("metrics") or {}).get("best", {}).get("metrics", {})
        active_model["primary_metric"] = "mae"
        active_model["primary_metric_value"] = best_metrics.get("mae")

    return {
        "registry_ready": True,
        "model_count": int(total or 0),
        "active_model": active_model,
    }


def list_model_versions(db: Session, limit: int = 50) -> list[dict[str, Any]]:
    try:
        rows = db.execute(text("""
            SELECT id, model_name, algorithm, target_name, business_category,
                   is_active, created_at, activated_at, metrics
            FROM ml.model_versions
            ORDER BY created_at DESC
            LIMIT :limit
        """), {"limit": limit}).mappings().all()
    except Exception:
        return []
    versions = []
    for r in rows:
        row = dict(r)
        best = (row.get("metrics") or {}).get("best", {})
        row["primary_metric"] = "mae"
        row["primary_metric_value"] = best.get("metrics", {}).get("mae")
        versions.append(row)
    return versions


def list_model_metrics(db: Session, model_version_id: int | None = None, limit: int = 200) -> list[dict[str, Any]]:
    """Per-candidate-model metrics from the comparison stored on ml.model_versions.metrics
    (there is no separate metrics table - one training run compares several models at once
    and keeps the full comparison, not just the winner)."""
    try:
        if model_version_id:
            rows = db.execute(text("SELECT id, metrics, created_at FROM ml.model_versions WHERE id = :id"), {"id": model_version_id}).mappings().all()
        else:
            rows = db.execute(text("SELECT id, metrics, created_at FROM ml.model_versions ORDER BY created_at DESC LIMIT :limit"), {"limit": limit}).mappings().all()
    except Exception:
        return []

    out = []
    for row in rows:
        candidates = (row["metrics"] or {}).get("all_candidates", [])
        for candidate in candidates:
            for metric_name, metric_value in (candidate.get("metrics") or {}).items():
                out.append({
                    "model_version_id": row["id"],
                    "algorithm": candidate.get("algorithm"),
                    "metric_name": metric_name,
                    "metric_value": metric_value,
                    "created_at": row["created_at"],
                })
    return out[:limit]


def list_feature_importance(db: Session, model_version_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """SHAP-based feature importance, computed once during training and stored on
    ml.model_versions.metrics.shap_top_features (see scripts/train_and_score_opportunity_model.py)."""
    try:
        if model_version_id:
            row = db.execute(text("SELECT id, metrics FROM ml.model_versions WHERE id = :id"), {"id": model_version_id}).mappings().first()
        else:
            row = db.execute(text("SELECT id, metrics FROM ml.model_versions WHERE is_active = TRUE LIMIT 1")).mappings().first()
    except Exception:
        return []
    if not row:
        return []
    shap_features = (row["metrics"] or {}).get("shap_top_features") or []
    return [
        {
            "model_version_id": row["id"],
            "feature_name": f["feature"],
            "importance_value": f["mean_abs_shap"],
            "rank": idx + 1,
            "source": "shap_mean_abs",
        }
        for idx, f in enumerate(shap_features[:limit])
    ]


@lru_cache(maxsize=8)
def load_model_artifact(artifact_uri: str) -> Any:
    path = Path(artifact_uri)
    if not path.is_absolute():
        path = _artifact_root() / artifact_uri
    if not path.exists():
        raise FileNotFoundError(f"Model artifact not found: {path}")
    return joblib.load(path)


def load_feature_schema(schema_uri: str | None) -> dict[str, Any] | None:
    if not schema_uri:
        return None
    path = Path(schema_uri)
    if not path.is_absolute():
        path = _artifact_root() / schema_uri
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
