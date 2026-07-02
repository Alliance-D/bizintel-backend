"""Score the full grid-category table with the active/best Phase 7 model.

This reads ml.grid_category_features, loads a trained sklearn Pipeline artifact,
and writes ml.ml_opportunity_predictions for map tiles, Scout Mode, and reports.

Example:
    DATABASE_URL=... python scripts/score_phase7_opportunity_grid.py \
      --model data/models/phase7/regression/best_model.joblib \
      --schema data/models/phase7/regression/feature_schema.json
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

ID_TARGET_COLUMNS = {
    "id", "geom", "centroid", "generated_at", "opportunity_gap_score", "presence_target",
    "business_count_target", "ranking_relevance", "opportunity_rank", "model_version_id",
}


def get_engine():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is required.")
    return create_engine(database_url)


def load_rows(limit: int | None = None) -> pd.DataFrame:
    limit_sql = "" if limit is None else f"LIMIT {int(limit)}"
    query = f"""
        SELECT *, ST_AsText(centroid) AS centroid_wkt, ST_X(centroid) AS longitude, ST_Y(centroid) AS latitude
        FROM ml.grid_category_features
        {limit_sql}
    """
    return pd.read_sql_query(text(query), get_engine())


def select_features(df: pd.DataFrame, schema_path: Path | None) -> pd.DataFrame:
    if schema_path and schema_path.exists():
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        cols = schema.get("feature_columns") or schema.get("input_columns")
        if cols:
            for col in cols:
                if col not in df.columns:
                    df[col] = "unknown" if col == "business_category" else 0
            return df[cols]
    cols = [c for c in df.columns if c not in ID_TARGET_COLUMNS and not c.startswith("Unnamed")]
    return df[cols]


def opportunity_type(score: float, confidence: float) -> str:
    if confidence < 40:
        return "Low-confidence estimate"
    if score >= 82:
        return "High-opportunity zone"
    if score >= 68:
        return "Promising opportunity"
    if score >= 52:
        return "Moderate opportunity"
    if score >= 35:
        return "Weak-demand or high-risk zone"
    return "Low opportunity"


def build_explanation(row: pd.Series, score: float) -> dict:
    drivers = {
        "demand": float(row.get("demand_score", 0) or 0),
        "accessibility": float(row.get("accessibility_score", 0) or 0),
        "commercial_activity": float(row.get("commercial_activity_score", 0) or 0),
        "competition_pressure": float(row.get("competition_pressure", 0) or 0),
        "confidence": float(row.get("confidence_score", 0) or 0),
    }
    strongest = sorted(drivers.items(), key=lambda item: item[1], reverse=True)[:2]
    risk = "competition" if drivers["competition_pressure"] > 70 else "data_confidence" if drivers["confidence"] < 45 else "balanced"
    return {
        "score": round(score, 2),
        "top_positive_drivers": strongest,
        "main_risk": risk,
        "plain_language": "Opportunity is estimated from demand, accessibility, commercial activity, supply pressure and data confidence.",
    }


def write_predictions(df: pd.DataFrame, scores: np.ndarray, model_version_id: int | None = None):
    engine = get_engine()
    out = df[["grid_id", "business_category", "centroid_wkt", "demand_score", "accessibility_score", "commercial_activity_score", "competition_pressure", "confidence_score"]].copy()
    out["opportunity_score"] = np.clip(scores, 0, 100)
    out["opportunity_rank"] = out.groupby("business_category")["opportunity_score"].rank(pct=True)
    out["opportunity_type"] = [opportunity_type(s, c) for s, c in zip(out["opportunity_score"], out["confidence_score"])]
    out["explanation"] = [json.dumps(build_explanation(df.iloc[i], out.iloc[i]["opportunity_score"])) for i in range(len(out))]

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM ml.ml_opportunity_predictions WHERE model_version_id IS NOT DISTINCT FROM :mv"), {"mv": model_version_id})
        for _, row in out.iterrows():
            conn.execute(text("""
                INSERT INTO ml.ml_opportunity_predictions (
                    grid_id, business_category, opportunity_score, opportunity_rank,
                    demand_score, accessibility_score, commercial_activity_score, competition_pressure,
                    confidence_score, opportunity_type, explanation, model_version_id, geom
                ) VALUES (
                    :grid_id, :business_category, :opportunity_score, :opportunity_rank,
                    :demand_score, :accessibility_score, :commercial_activity_score, :competition_pressure,
                    :confidence_score, :opportunity_type, CAST(:explanation AS jsonb), :model_version_id,
                    ST_GeomFromText(:centroid_wkt, 4326)
                )
                ON CONFLICT DO NOTHING
            """), {
                "grid_id": row["grid_id"],
                "business_category": row["business_category"],
                "opportunity_score": float(row["opportunity_score"]),
                "opportunity_rank": float(row["opportunity_rank"]),
                "demand_score": float(row["demand_score"] or 0),
                "accessibility_score": float(row["accessibility_score"] or 0),
                "commercial_activity_score": float(row["commercial_activity_score"] or 0),
                "competition_pressure": float(row["competition_pressure"] or 0),
                "confidence_score": float(row["confidence_score"] or 0),
                "opportunity_type": row["opportunity_type"],
                "explanation": row["explanation"],
                "model_version_id": model_version_id,
                "centroid_wkt": row["centroid_wkt"],
            })
    print(f"Wrote {len(out):,} ML opportunity predictions.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--schema", default=None)
    parser.add_argument("--model-version-id", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    df = load_rows(args.limit)
    if df.empty:
        raise RuntimeError("ml.grid_category_features is empty.")
    model = joblib.load(args.model)
    X = select_features(df, Path(args.schema) if args.schema else None)
    scores = model.predict(X)
    write_predictions(df, scores, args.model_version_id)


if __name__ == "__main__":
    main()
