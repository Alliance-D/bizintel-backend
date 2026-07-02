"""Generate cached opportunity predictions for Opportunity Map Mode.

This script is intentionally conservative: it reads ml.training_features-like rows,
uses the active registered model, and writes map-ready prediction summaries into
ml.opportunity_predictions_cache. In production this can be run as a background
job after every approved model activation.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import joblib
import pandas as pd
from sqlalchemy import create_engine, text


def get_engine():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is required.")
    return create_engine(database_url)


def classify(score: float) -> str:
    if score >= 78:
        return "High opportunity"
    if score >= 62:
        return "Underserved / promising"
    if score >= 45:
        return "Moderate opportunity"
    return "Weak opportunity"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    engine = get_engine()
    with engine.begin() as conn:
        model = conn.execute(text("""
            SELECT * FROM ml.model_versions
            WHERE is_active = TRUE
            ORDER BY activated_at DESC NULLS LAST, created_at DESC
            LIMIT 1
        """)).mappings().first()
        if not model:
            raise RuntimeError("No active model registered.")

        schema = json.loads(Path(model["feature_schema_uri"]).read_text(encoding="utf-8"))
        feature_cols = schema["feature_columns"]
        where = "WHERE business_category = :category" if args.category else ""
        limit_sql = f"LIMIT {int(args.limit)}" if args.limit else ""
        params = {"category": args.category} if args.category else {}

        df = pd.read_sql_query(text(f"SELECT * FROM ml.training_features {where} {limit_sql}"), conn, params=params)
        if df.empty:
            raise RuntimeError("No training feature rows found for cache generation.")

        pipe = joblib.load(model["artifact_uri"])
        for col in feature_cols:
            if col not in df.columns:
                df[col] = "unknown" if col == "business_category" else 0
        scores = pipe.predict(df[feature_cols])
        scores = [float(max(0, min(100, s))) for s in scores]

        conn.execute(text("DELETE FROM ml.opportunity_predictions_cache WHERE model_version_id = :model_id"), {"model_id": model["id"]})
        for idx, score in enumerate(scores):
            row = df.iloc[idx]
            conn.execute(text("""
                INSERT INTO ml.opportunity_predictions_cache (
                    grid_id, business_category, model_version_id, opportunity_score,
                    saturation_score, opportunity_gap_score, confidence_score,
                    opportunity_class, explanation, geom
                ) VALUES (
                    :grid_id, :business_category, :model_version_id, :opportunity_score,
                    :saturation_score, :opportunity_gap_score, :confidence_score,
                    :opportunity_class, CAST(:explanation AS JSONB),
                    CASE WHEN :lon IS NOT NULL AND :lat IS NOT NULL
                        THEN ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
                        ELSE NULL END
                )
            """), {
                "grid_id": int(row.get("grid_id", 0)) if pd.notna(row.get("grid_id", None)) else None,
                "business_category": row.get("business_category", "general"),
                "model_version_id": model["id"],
                "opportunity_score": score,
                "saturation_score": float(row.get("competition_pressure", row.get("competitor_count_500m", 0)) or 0),
                "opportunity_gap_score": score,
                "confidence_score": float(row.get("confidence_score", 65) or 65),
                "opportunity_class": classify(score),
                "explanation": json.dumps({"model": model["model_name"], "score_source": "active_model"}),
                "lon": float(row.get("longitude")) if "longitude" in row and pd.notna(row.get("longitude")) else None,
                "lat": float(row.get("latitude")) if "latitude" in row and pd.notna(row.get("latitude")) else None,
            })
    print(f"Cached {len(scores):,} predictions for model {model['id']}.")


if __name__ == "__main__":
    main()
