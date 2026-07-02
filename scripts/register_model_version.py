"""Register a trained Phase 3 model artifact in PostGIS model registry."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sqlalchemy import create_engine, text


def get_engine():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is required.")
    return create_engine(database_url)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics-json", required=True, help="Metrics JSON produced by train_model_suite.py")
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()

    summary = json.loads(Path(args.metrics_json).read_text(encoding="utf-8"))
    artifact_path = summary["artifact_path"]
    feature_schema_path = summary["feature_schema_path"]
    importance_path = summary.get("feature_importance_path")

    task = summary["task"]
    task_type = "regression" if task in {"regression", "count"} else "classification"
    if task == "count":
        task_type = "count"

    primary_metric = summary["primary_metric"]
    primary_metric_value = summary["primary_metric_value"]
    if primary_metric_value is not None:
        primary_metric_value = float(primary_metric_value)

    engine = get_engine()
    with engine.begin() as conn:
        if args.activate:
            conn.execute(text("UPDATE ml.model_versions SET is_active = FALSE WHERE task_type = :task_type AND target_name = :target"), {
                "task_type": task_type,
                "target": summary["target"],
            })
        model_id = conn.execute(text("""
            INSERT INTO ml.model_versions (
                model_name, model_family, task_type, business_scope, target_name,
                feature_set_name, artifact_uri, feature_schema_uri, metrics_uri,
                explanation_uri, validation_strategy, primary_metric,
                primary_metric_value, metrics, feature_columns, category_columns,
                numeric_columns, training_rows, validation_rows, model_notes,
                is_active, activated_at
            ) VALUES (
                :model_name, :model_family, :task_type, 'multi_category', :target_name,
                'phase3_grid_category_features', :artifact_uri, :feature_schema_uri, :metrics_uri,
                :explanation_uri, :validation_strategy, :primary_metric,
                :primary_metric_value, CAST(:metrics AS JSONB), CAST(:feature_columns AS JSONB), CAST(:category_columns AS JSONB),
                CAST(:numeric_columns AS JSONB), :training_rows, :validation_rows, :model_notes,
                :is_active, CASE WHEN :is_active THEN now() ELSE NULL END
            ) RETURNING id
        """), {
            "model_name": summary["best_model"],
            "model_family": summary["best_model"].split("_")[0],
            "task_type": task_type,
            "target_name": summary["target"],
            "artifact_uri": artifact_path,
            "feature_schema_uri": feature_schema_path,
            "metrics_uri": args.metrics_json,
            "explanation_uri": importance_path,
            "validation_strategy": summary.get("split_strategy", "spatial_group_validation"),
            "primary_metric": primary_metric,
            "primary_metric_value": primary_metric_value,
            "metrics": json.dumps(summary.get("best_metrics", {})),
            "feature_columns": json.dumps(json.loads(Path(feature_schema_path).read_text(encoding="utf-8")).get("feature_columns", [])),
            "category_columns": json.dumps(json.loads(Path(feature_schema_path).read_text(encoding="utf-8")).get("categorical_columns", [])),
            "numeric_columns": json.dumps(json.loads(Path(feature_schema_path).read_text(encoding="utf-8")).get("numeric_columns", [])),
            "training_rows": summary.get("training_rows"),
            "validation_rows": summary.get("validation_rows"),
            "model_notes": f"Registered from {args.metrics_json}",
            "is_active": bool(args.activate),
        }).scalar_one()

        for split_name, metrics in [("validation", summary.get("best_metrics", {}))]:
            for metric_name, metric_value in metrics.items():
                conn.execute(text("""
                    INSERT INTO ml.model_metrics (model_version_id, split_name, metric_name, metric_value)
                    VALUES (:model_id, :split_name, :metric_name, :metric_value)
                """), {
                    "model_id": model_id,
                    "split_name": split_name,
                    "metric_name": metric_name,
                    "metric_value": float(metric_value),
                })

        if importance_path and Path(importance_path).exists():
            importances = json.loads(Path(importance_path).read_text(encoding="utf-8"))
            for row in importances:
                conn.execute(text("""
                    INSERT INTO ml.feature_importance (model_version_id, feature_name, importance_value, rank, source)
                    VALUES (:model_id, :feature_name, :importance_value, :rank, 'model_importance')
                """), {
                    "model_id": model_id,
                    "feature_name": row["feature_name"],
                    "importance_value": float(row["importance_value"]),
                    "rank": int(row.get("rank") or 0),
                })

    print(f"Registered model version {model_id}. Active={args.activate}")


if __name__ == "__main__":
    main()
