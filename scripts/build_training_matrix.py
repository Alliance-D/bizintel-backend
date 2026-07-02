"""Build the model-ready training matrix for Phase 3.

Unit of analysis:
    one row = one Kigali grid cell + one business category

This script reads ml.training_features from PostGIS and exports a clean matrix
used by train_model_suite.py. It also creates robust targets when they are
available or derivable:

- opportunity_gap_score: main regression/ranking target.
- presence_target: binary target derived from category business count or
  competitor/business count when a direct presence column is not available.
- business_count_target: count target for count/density models.

The script deliberately avoids raw microdata. It expects Phase 2 curated and
feature-generation tables to already exist.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

DEFAULT_OUTPUT = Path("data/processed/training_matrix_phase3.csv")

ID_COLUMNS = {
    "id", "grid_id", "cell_id", "sector_id", "district_id", "province_id",
    "geom", "geometry", "centroid", "created_at", "updated_at", "generated_at",
}


def get_engine():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is required.")
    return create_engine(database_url)


def load_training_features(limit: int | None = None) -> pd.DataFrame:
    limit_sql = "" if limit is None else f"LIMIT {int(limit)}"
    query = f"""
        SELECT *
        FROM ml.training_features
        {limit_sql}
    """
    engine = get_engine()
    return pd.read_sql_query(text(query), engine)


def derive_targets(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    if "opportunity_gap_score" not in df.columns:
        # Defensive fallback if an older Phase 2 table exists.
        demand = df.get("demand_score", 0)
        access = df.get("access_score", df.get("accessibility_score", 0))
        commercial = df.get("commercial_activity_score", 0)
        comp = df.get("competitor_count_500m", 0)
        comp_penalty = np.minimum(100, pd.Series(comp).fillna(0) * 8)
        df["opportunity_gap_score"] = np.clip(
            0.40 * pd.Series(demand).fillna(0)
            + 0.25 * pd.Series(access).fillna(0)
            + 0.25 * pd.Series(commercial).fillna(0)
            + 0.10 * (100 - comp_penalty),
            0,
            100,
        )

    count_candidates = [
        "business_count",
        "category_business_count",
        "same_category_business_count",
        "competitor_count_500m",
        "competitor_count_1000m",
    ]
    count_col = next((c for c in count_candidates if c in df.columns), None)
    if count_col:
        df["business_count_target"] = pd.to_numeric(df[count_col], errors="coerce").fillna(0).clip(lower=0)
    else:
        df["business_count_target"] = 0

    if "presence_target" not in df.columns:
        df["presence_target"] = (df["business_count_target"] > 0).astype(int)

    # Ranking relevance: high opportunity gets higher relevance grade.
    if "ranking_relevance" not in df.columns:
        q = df["opportunity_gap_score"].rank(pct=True)
        df["ranking_relevance"] = pd.cut(
            q,
            bins=[0, 0.40, 0.70, 0.90, 1.0],
            labels=[0, 1, 2, 3],
            include_lowest=True,
        ).astype(int)

    return df


def clean_matrix(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "business_category" not in df.columns:
        df["business_category"] = "general"

    for col in df.columns:
        if df[col].dtype == "object":
            df[col] = df[col].fillna("unknown")
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


def write_feature_manifest(df: pd.DataFrame, output_csv: Path) -> Path:
    manifest = output_csv.with_suffix(".feature_manifest.csv")
    rows = []
    for col in df.columns:
        role = "feature"
        if col in ID_COLUMNS:
            role = "identifier"
        if col in {"opportunity_gap_score", "presence_target", "business_count_target", "ranking_relevance"}:
            role = "target"
        if col == "business_category":
            role = "categorical_feature"
        rows.append({"column": col, "dtype": str(df[col].dtype), "role": role})
    pd.DataFrame(rows).to_csv(manifest, index=False)
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    df = load_training_features(limit=args.limit)
    if df.empty:
        raise RuntimeError("ml.training_features is empty. Run Phase 2 feature generation first.")

    df = derive_targets(df)
    df = clean_matrix(df)
    df.to_csv(output, index=False)
    manifest = write_feature_manifest(df, output)

    print(f"Wrote training matrix: {output} ({len(df):,} rows, {len(df.columns):,} columns)")
    print(f"Wrote feature manifest: {manifest}")


if __name__ == "__main__":
    main()
