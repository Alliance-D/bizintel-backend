from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings


def _artifact_root() -> Path:
    settings = get_settings()
    return Path(os.getenv("MODEL_ARTIFACT_DIR", "ml/artifacts")).expanduser().resolve()


def model_status(db: Session) -> dict[str, Any]:
    """Return registry status and active model metadata.

    The backend remains usable even before the SQL registry has been created.
    """
    try:
        total = db.execute(text("SELECT COUNT(*) FROM ml.model_versions")).scalar_one()
        active = db.execute(text("""
            SELECT id, model_name, model_family, task_type, target_name,
                   primary_metric, primary_metric_value, artifact_uri,
                   created_at, activated_at
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

    return {
        "registry_ready": True,
        "model_count": int(total or 0),
        "active_model": dict(active) if active else None,
    }


def list_model_versions(db: Session, limit: int = 50) -> list[dict[str, Any]]:
    try:
        rows = db.execute(text("""
            SELECT id, model_name, model_family, task_type, business_scope,
                   target_name, feature_set_name, primary_metric,
                   primary_metric_value, is_active, created_at, activated_at,
                   training_rows, validation_rows, model_notes
            FROM ml.model_versions
            ORDER BY created_at DESC
            LIMIT :limit
        """), {"limit": limit}).mappings().all()
    except Exception:
        return []
    return [dict(r) for r in rows]


def list_model_metrics(db: Session, model_version_id: int | None = None, limit: int = 200) -> list[dict[str, Any]]:
    try:
        if model_version_id:
            rows = db.execute(text("""
                SELECT model_version_id, split_name, metric_name, metric_value, created_at
                FROM ml.model_metrics
                WHERE model_version_id = :model_version_id
                ORDER BY split_name, metric_name
                LIMIT :limit
            """), {"model_version_id": model_version_id, "limit": limit}).mappings().all()
        else:
            rows = db.execute(text("""
                SELECT model_version_id, split_name, metric_name, metric_value, created_at
                FROM ml.model_metrics
                ORDER BY created_at DESC
                LIMIT :limit
            """), {"limit": limit}).mappings().all()
    except Exception:
        return []
    return [dict(r) for r in rows]


def list_feature_importance(db: Session, model_version_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
    try:
        if model_version_id:
            rows = db.execute(text("""
                SELECT model_version_id, feature_name, importance_value, rank, source
                FROM ml.feature_importance
                WHERE model_version_id = :model_version_id
                ORDER BY rank NULLS LAST, importance_value DESC
                LIMIT :limit
            """), {"model_version_id": model_version_id, "limit": limit}).mappings().all()
        else:
            rows = db.execute(text("""
                SELECT fi.model_version_id, fi.feature_name, fi.importance_value, fi.rank, fi.source
                FROM ml.feature_importance fi
                JOIN ml.model_versions mv ON mv.id = fi.model_version_id
                WHERE mv.is_active = TRUE
                ORDER BY fi.rank NULLS LAST, fi.importance_value DESC
                LIMIT :limit
            """), {"limit": limit}).mappings().all()
    except Exception:
        return []
    return [dict(r) for r in rows]


def get_active_model_record(db: Session, task_type: str | None = None, target_name: str | None = None) -> dict[str, Any] | None:
    clauses = ["is_active = TRUE"]
    params: dict[str, Any] = {}
    if task_type:
        clauses.append("task_type = :task_type")
        params["task_type"] = task_type
    if target_name:
        clauses.append("target_name = :target_name")
        params["target_name"] = target_name
    where = " AND ".join(clauses)
    try:
        row = db.execute(text(f"""
            SELECT * FROM ml.model_versions
            WHERE {where}
            ORDER BY activated_at DESC NULLS LAST, created_at DESC
            LIMIT 1
        """), params).mappings().first()
    except Exception:
        return None
    return dict(row) if row else None


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
