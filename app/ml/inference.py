from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.geo.feature_extraction import LocationFeatures
from app.ml.model_registry import get_active_model_record, load_feature_schema, load_model_artifact


CORE_FEATURES = [
    "demand_score",
    "accessibility_score",
    "competition_pressure",
    "commercial_activity_score",
    "risk_score",
    "confidence_score",
    "population_density_500m",
    "population_density_1000m",
    "commercial_poi_count_500m",
    "competitor_count_300m",
    "competitor_count_500m",
    "competitor_count_1000m",
    "market_distance_m",
    "nearest_main_road_m",
    "bus_stop_count_500m",
]


def _fallback_prediction(features: LocationFeatures, business_category: str) -> dict[str, Any]:
    score = (
        features.demand_score * 0.30
        + features.accessibility_score * 0.25
        + features.commercial_activity_score * 0.25
        + (100 - features.competition_pressure) * 0.12
        + (100 - features.risk_score) * 0.08
    )
    score = round(max(0, min(100, score)), 2)

    if score >= 78:
        opportunity_type = "Strong opportunity"
    elif score >= 62:
        opportunity_type = "Promising but needs validation"
    elif score >= 45:
        opportunity_type = "Moderate opportunity"
    else:
        opportunity_type = "Weak opportunity"

    confidence = "high" if features.confidence_score >= 70 else "medium" if features.confidence_score >= 50 else "low"

    return {
        "score": score,
        "opportunity_type": opportunity_type,
        "confidence": confidence,
        "model_source": "fallback_scoring_contract",
        "model_version_id": None,
    }


def _to_model_frame(features: LocationFeatures, business_category: str, schema: dict[str, Any] | None) -> pd.DataFrame:
    row = asdict(features)
    row["business_category"] = business_category
    df = pd.DataFrame([row])

    # If training saved an exact input schema, honor it. Missing numeric features
    # become 0; missing categorical features become 'unknown'.
    if schema:
        feature_columns = schema.get("feature_columns") or schema.get("input_columns") or []
        categorical = set(schema.get("categorical_columns") or ["business_category"])
        for col in feature_columns:
            if col not in df.columns:
                df[col] = "unknown" if col in categorical else 0
        if feature_columns:
            return df[feature_columns]

    cols = [c for c in CORE_FEATURES if c in df.columns] + ["business_category"]
    return df[cols]


def predict_opportunity(features: LocationFeatures, business_category: str, db: Session | None = None) -> dict[str, Any]:
    """Predict opportunity score using the active model when available.

    Falls back to a deterministic scoring contract until Phase 3 models have been
    trained and registered. This keeps the app usable during data ingestion.
    """
    if db is None:
        return _fallback_prediction(features, business_category)

    record = get_active_model_record(db, task_type="regression", target_name="opportunity_gap_score")
    if not record:
        record = get_active_model_record(db)
    if not record:
        return _fallback_prediction(features, business_category)

    try:
        artifact = load_model_artifact(record["artifact_uri"])
        schema = load_feature_schema(record.get("feature_schema_uri"))
        X = _to_model_frame(features, business_category, schema)

        if hasattr(artifact, "predict_proba") and record.get("task_type") == "classification":
            pred = float(artifact.predict_proba(X)[0, 1]) * 100.0
        else:
            pred = float(artifact.predict(X)[0])

        score = round(max(0, min(100, pred)), 2)
    except Exception:
        return _fallback_prediction(features, business_category)

    if score >= 78:
        opportunity_type = "Strong opportunity"
    elif score >= 62:
        opportunity_type = "Promising but needs validation"
    elif score >= 45:
        opportunity_type = "Moderate opportunity"
    else:
        opportunity_type = "Weak opportunity"

    confidence = "high" if features.confidence_score >= 70 else "medium" if features.confidence_score >= 50 else "low"
    return {
        "score": score,
        "opportunity_type": opportunity_type,
        "confidence": confidence,
        "model_source": record.get("model_name"),
        "model_version_id": record.get("id"),
    }
