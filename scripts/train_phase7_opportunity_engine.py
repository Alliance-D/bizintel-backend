"""Train Phase 7 ML opportunity engine from ml.grid_category_features.

This is the production-oriented training entry point for the redesigned system:
- one row = one grid cell + one business category
- multiple model families are compared
- regression, presence classification, and count/density targets are supported
- the best artifact, feature schema, metrics, and feature importance are saved

Example:
    DATABASE_URL=... python scripts/train_phase7_opportunity_engine.py --task regression
    DATABASE_URL=... python scripts/train_phase7_opportunity_engine.py --task classification
    DATABASE_URL=... python scripts/train_phase7_opportunity_engine.py --task count
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = PROJECT_ROOT / "data" / "processed" / "training_matrix_phase7.csv"
DEFAULT_ARTIFACTS = PROJECT_ROOT / "data" / "models" / "phase7"


def get_engine():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is required.")
    return create_engine(database_url)


def export_training_matrix(output: Path, limit: int | None = None) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    limit_sql = "" if limit is None else f"LIMIT {int(limit)}"
    query = f"""
        SELECT
            grid_id,
            business_category,
            district,
            sector,
            cell,
            ST_X(centroid) AS longitude,
            ST_Y(centroid) AS latitude,
            population_density_500m,
            population_density_1000m,
            sector_population,
            youth_share,
            female_share,
            household_density_proxy,
            employment_rate,
            income_proxy,
            welfare_proxy,
            poverty_proxy,
            nearest_main_road_m,
            road_access_score,
            bus_stop_count_500m,
            nearest_bus_stop_m,
            mobility_local_share,
            commercial_poi_count_500m,
            demand_generator_count_1000m,
            complementary_poi_count_500m,
            market_distance_m,
            school_count_1000m,
            health_facility_count_1000m,
            business_diversity_index,
            competitor_count_300m,
            competitor_count_500m,
            competitor_count_1000m,
            establishment_category_count_area,
            establishment_density_area,
            supply_pressure_score,
            demand_score,
            accessibility_score,
            commercial_activity_score,
            competition_pressure,
            welfare_score,
            opportunity_gap_score,
            confidence_score,
            presence_target,
            business_count_target,
            ranking_relevance
        FROM ml.grid_category_features
        {limit_sql}
    """
    df = pd.read_sql_query(text(query), get_engine())
    if df.empty:
        raise RuntimeError("ml.grid_category_features is empty. Run build_grid_category_features.py first.")
    df.to_csv(output, index=False)
    print(f"Exported Phase 7 training matrix: {output} ({len(df):,} rows)")
    return output


def run_training(matrix: Path, task: str, artifacts: Path) -> Path:
    artifacts.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "train_model_suite.py"),
        "--input",
        str(matrix),
        "--task",
        task,
        "--output-dir",
        str(artifacts / task),
    ]
    print("Running:", " ".join(cmd))
    subprocess.check_call(cmd)
    return artifacts / task


def write_run_manifest(task: str, matrix: Path, artifact_dir: Path) -> Path:
    manifest = {
        "phase": "phase7",
        "task": task,
        "matrix": str(matrix),
        "artifact_dir": str(artifact_dir),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "ML-backed spatial opportunity engine for grid-cell + business-category predictions.",
        "unit_of_analysis": "one row = one grid cell + one business category",
    }
    out = artifact_dir / "phase7_run_manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=["regression", "classification", "count"], default="regression")
    parser.add_argument("--matrix", default=str(DEFAULT_MATRIX))
    parser.add_argument("--artifact-dir", default=str(DEFAULT_ARTIFACTS))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--skip-export", action="store_true")
    args = parser.parse_args()

    matrix = Path(args.matrix)
    if not args.skip_export:
        export_training_matrix(matrix, args.limit)
    artifact_dir = run_training(matrix, args.task, Path(args.artifact_dir))
    manifest = write_run_manifest(args.task, matrix, artifact_dir)
    print(f"Wrote Phase 7 manifest: {manifest}")


if __name__ == "__main__":
    main()
