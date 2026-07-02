"""Train and compare Phase 3 ML model candidates.

This trains multiple model families instead of committing to one algorithm too
early. It supports three immediate tasks:

1. Regression: predict opportunity_gap_score.
2. Classification: predict presence_target.
3. Count regression: predict business_count_target.

The best model is selected by task-appropriate validation metrics and saved to
an artifact folder. The model is a full sklearn Pipeline including preprocessing
so backend inference can load it directly.

Example:
    python scripts/train_model_suite.py --input data/processed/training_matrix_phase3.csv --task regression
    python scripts/train_model_suite.py --input data/processed/training_matrix_phase3.csv --task classification
"""
from __future__ import annotations

import argparse
import json
import math
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesClassifier, ExtraTreesRegressor, RandomForestClassifier, RandomForestRegressor, HistGradientBoostingRegressor, HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, PoissonRegressor, Ridge
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
    roc_auc_score,
)
from sklearn.model_selection import GroupShuffleSplit, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

warnings.filterwarnings("ignore", category=UserWarning)

try:
    from lightgbm import LGBMClassifier, LGBMRegressor
except Exception:  # pragma: no cover
    LGBMClassifier = None
    LGBMRegressor = None

try:
    from xgboost import XGBClassifier, XGBRegressor
except Exception:  # pragma: no cover
    XGBClassifier = None
    XGBRegressor = None

try:
    from catboost import CatBoostClassifier, CatBoostRegressor
except Exception:  # pragma: no cover
    CatBoostClassifier = None
    CatBoostRegressor = None

ID_COLUMNS = {
    "id", "grid_id", "cell_id", "sector_id", "district_id", "province_id",
    "geom", "geometry", "centroid", "created_at", "updated_at", "generated_at",
}
TARGET_BY_TASK = {
    "regression": "opportunity_gap_score",
    "classification": "presence_target",
    "count": "business_count_target",
}
TARGET_COLUMNS = set(TARGET_BY_TASK.values()) | {"ranking_relevance"}


def load_data(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def choose_features(df: pd.DataFrame, target: str) -> tuple[list[str], list[str], list[str]]:
    excluded = ID_COLUMNS | TARGET_COLUMNS | {target}
    candidate_cols = [c for c in df.columns if c not in excluded]
    categorical = []
    numeric = []
    for col in candidate_cols:
        if col == "business_category" or df[col].dtype == "object" or str(df[col].dtype).startswith("category"):
            categorical.append(col)
        else:
            numeric.append(col)
    return candidate_cols, numeric, categorical


def split_data(df: pd.DataFrame, target: str):
    y = df[target]
    groups = None
    for candidate in ["sector_id", "cell_id", "district_id", "grid_id"]:
        if candidate in df.columns and df[candidate].nunique() > 2:
            groups = df[candidate]
            break

    if groups is not None and len(df) >= 20:
        splitter = GroupShuffleSplit(n_splits=1, test_size=0.20, random_state=42)
        train_idx, test_idx = next(splitter.split(df, y, groups=groups))
        return df.iloc[train_idx].copy(), df.iloc[test_idx].copy(), f"group_shuffle_split_by_{candidate}"

    train, test = train_test_split(df, test_size=0.20, random_state=42, stratify=y if target == "presence_target" and y.nunique() == 2 else None)
    return train.copy(), test.copy(), "random_split_fallback"


def build_preprocessor(numeric: list[str], categorical: list[str]) -> ColumnTransformer:
    numeric_pipe = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
    ])
    categorical_pipe = Pipeline([
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("onehot", OneHotEncoder(handle_unknown="ignore", min_frequency=5)),
    ])
    return ColumnTransformer([
        ("num", numeric_pipe, numeric),
        ("cat", categorical_pipe, categorical),
    ], remainder="drop")


def candidate_models(task: str) -> dict[str, Any]:
    models: dict[str, Any] = {}
    if task == "classification":
        models.update({
            "logistic_regression": LogisticRegression(max_iter=1000, class_weight="balanced"),
            "random_forest": RandomForestClassifier(n_estimators=250, max_depth=None, min_samples_leaf=3, random_state=42, n_jobs=-1, class_weight="balanced"),
            "extra_trees": ExtraTreesClassifier(n_estimators=300, min_samples_leaf=3, random_state=42, n_jobs=-1, class_weight="balanced"),
            "hist_gradient_boosting": HistGradientBoostingClassifier(max_iter=250, learning_rate=0.06, random_state=42),
        })
        if LGBMClassifier:
            models["lightgbm"] = LGBMClassifier(n_estimators=400, learning_rate=0.04, num_leaves=31, random_state=42, class_weight="balanced")
        if XGBClassifier:
            models["xgboost"] = XGBClassifier(n_estimators=350, learning_rate=0.04, max_depth=5, subsample=0.85, colsample_bytree=0.85, eval_metric="logloss", random_state=42)
        if CatBoostClassifier:
            models["catboost"] = CatBoostClassifier(iterations=350, learning_rate=0.04, depth=6, verbose=False, random_seed=42)
    elif task == "count":
        models.update({
            "poisson_regression": PoissonRegressor(alpha=0.1, max_iter=1000),
            "random_forest_count": RandomForestRegressor(n_estimators=250, min_samples_leaf=3, random_state=42, n_jobs=-1),
            "extra_trees_count": ExtraTreesRegressor(n_estimators=300, min_samples_leaf=3, random_state=42, n_jobs=-1),
            "hist_gradient_boosting_count": HistGradientBoostingRegressor(max_iter=250, learning_rate=0.06, loss="poisson", random_state=42),
        })
        if LGBMRegressor:
            models["lightgbm_count"] = LGBMRegressor(n_estimators=400, learning_rate=0.04, objective="poisson", random_state=42)
        if XGBRegressor:
            models["xgboost_count"] = XGBRegressor(n_estimators=350, learning_rate=0.04, max_depth=5, objective="count:poisson", random_state=42)
        if CatBoostRegressor:
            models["catboost_count"] = CatBoostRegressor(iterations=350, learning_rate=0.04, depth=6, loss_function="Poisson", verbose=False, random_seed=42)
    else:
        models.update({
            "ridge_baseline": Ridge(alpha=1.0),
            "random_forest": RandomForestRegressor(n_estimators=250, min_samples_leaf=3, random_state=42, n_jobs=-1),
            "extra_trees": ExtraTreesRegressor(n_estimators=300, min_samples_leaf=3, random_state=42, n_jobs=-1),
            "hist_gradient_boosting": HistGradientBoostingRegressor(max_iter=250, learning_rate=0.06, random_state=42),
        })
        if LGBMRegressor:
            models["lightgbm"] = LGBMRegressor(n_estimators=450, learning_rate=0.035, num_leaves=31, random_state=42)
        if XGBRegressor:
            models["xgboost"] = XGBRegressor(n_estimators=400, learning_rate=0.035, max_depth=5, subsample=0.85, colsample_bytree=0.85, random_state=42)
        if CatBoostRegressor:
            models["catboost"] = CatBoostRegressor(iterations=400, learning_rate=0.035, depth=6, verbose=False, random_seed=42)
    return models


def evaluate(task: str, y_true, pred, proba=None) -> dict[str, float]:
    metrics: dict[str, float] = {}
    if task == "classification":
        pred_label = (proba >= 0.5).astype(int) if proba is not None else pred
        metrics["accuracy"] = float(accuracy_score(y_true, pred_label))
        metrics["f1"] = float(f1_score(y_true, pred_label, zero_division=0))
        if proba is not None and len(np.unique(y_true)) == 2:
            metrics["roc_auc"] = float(roc_auc_score(y_true, proba))
            metrics["average_precision"] = float(average_precision_score(y_true, proba))
    else:
        metrics["mae"] = float(mean_absolute_error(y_true, pred))
        metrics["rmse"] = float(math.sqrt(mean_squared_error(y_true, pred)))
        metrics["r2"] = float(r2_score(y_true, pred))
    return metrics


def primary_score(task: str, metrics: dict[str, float]) -> float:
    if task == "classification":
        return metrics.get("roc_auc", metrics.get("f1", 0.0))
    # lower RMSE is better, so invert for selection.
    return -metrics.get("rmse", float("inf"))


def get_feature_importance(pipe: Pipeline, feature_columns: list[str]) -> list[dict[str, Any]]:
    model = pipe.named_steps.get("model")
    importances = getattr(model, "feature_importances_", None)
    if importances is None:
        return []
    # For one-hot pipelines, exact transformed names can be lengthy; capture them when possible.
    try:
        names = pipe.named_steps["preprocess"].get_feature_names_out().tolist()
    except Exception:
        names = feature_columns
    rows = []
    for i, val in enumerate(importances):
        name = names[i] if i < len(names) else f"feature_{i}"
        rows.append({"feature_name": name, "importance_value": float(val)})
    rows = sorted(rows, key=lambda r: r["importance_value"], reverse=True)
    for idx, row in enumerate(rows, start=1):
        row["rank"] = idx
    return rows[:100]


def train_suite(df: pd.DataFrame, task: str, output_dir: Path) -> dict[str, Any]:
    target = TARGET_BY_TASK[task]
    if target not in df.columns:
        raise RuntimeError(f"Target column missing: {target}")
    if task == "classification" and df[target].nunique() < 2:
        raise RuntimeError("presence_target has only one class. Need both presence and background/zero examples.")

    feature_columns, numeric, categorical = choose_features(df, target)
    train_df, valid_df, split_strategy = split_data(df, target)
    X_train, y_train = train_df[feature_columns], train_df[target]
    X_valid, y_valid = valid_df[feature_columns], valid_df[target]

    results = []
    best = None
    output_dir.mkdir(parents=True, exist_ok=True)

    for name, estimator in candidate_models(task).items():
        print(f"Training {name}...")
        pipe = Pipeline([
            ("preprocess", build_preprocessor(numeric, categorical)),
            ("model", estimator),
        ])
        try:
            pipe.fit(X_train, y_train)
            if task == "classification" and hasattr(pipe, "predict_proba"):
                proba = pipe.predict_proba(X_valid)[:, 1]
                pred = (proba >= 0.5).astype(int)
            else:
                proba = None
                pred = pipe.predict(X_valid)
                if task == "count":
                    pred = np.clip(pred, 0, None)
            metrics = evaluate(task, y_valid, pred, proba)
            score = primary_score(task, metrics)
            result = {"model_name": name, "task": task, "metrics": metrics, "primary_score": score, "status": "ok"}
            results.append(result)
            if best is None or score > best["primary_score"]:
                best = {**result, "pipeline": pipe}
        except Exception as exc:
            results.append({"model_name": name, "task": task, "metrics": {}, "primary_score": None, "status": "failed", "error": str(exc)})

    if best is None:
        raise RuntimeError("No candidate model trained successfully.")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    model_slug = f"{task}_{best['model_name']}_{timestamp}"
    artifact_path = output_dir / f"{model_slug}.joblib"
    schema_path = output_dir / f"{model_slug}.feature_schema.json"
    metrics_path = output_dir / f"{model_slug}.metrics.json"
    importance_path = output_dir / f"{model_slug}.feature_importance.json"
    comparison_path = output_dir / f"{task}_model_comparison_{timestamp}.csv"

    joblib.dump(best["pipeline"], artifact_path)
    feature_schema = {
        "task": task,
        "target": target,
        "feature_columns": feature_columns,
        "numeric_columns": numeric,
        "categorical_columns": categorical,
        "split_strategy": split_strategy,
        "training_rows": int(len(train_df)),
        "validation_rows": int(len(valid_df)),
    }
    schema_path.write_text(json.dumps(feature_schema, indent=2), encoding="utf-8")

    comparison_rows = []
    for r in results:
        row = {"model_name": r["model_name"], "task": r["task"], "status": r["status"], "primary_score": r.get("primary_score")}
        row.update(r.get("metrics") or {})
        if "error" in r:
            row["error"] = r["error"]
        comparison_rows.append(row)
    pd.DataFrame(comparison_rows).to_csv(comparison_path, index=False)

    importances = get_feature_importance(best["pipeline"], feature_columns)
    importance_path.write_text(json.dumps(importances, indent=2), encoding="utf-8")

    summary = {
        "task": task,
        "target": target,
        "best_model": best["model_name"],
        "best_metrics": best["metrics"],
        "primary_metric": "roc_auc" if task == "classification" else "rmse",
        "primary_metric_value": best["metrics"].get("roc_auc") if task == "classification" else best["metrics"].get("rmse"),
        "selection_score": best["primary_score"],
        "split_strategy": split_strategy,
        "artifact_path": str(artifact_path),
        "feature_schema_path": str(schema_path),
        "metrics_path": str(metrics_path),
        "feature_importance_path": str(importance_path),
        "comparison_path": str(comparison_path),
        "training_rows": int(len(train_df)),
        "validation_rows": int(len(valid_df)),
        "candidate_results": results,
    }
    metrics_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="CSV or Parquet training matrix path")
    parser.add_argument("--task", choices=["regression", "classification", "count"], default="regression")
    parser.add_argument("--output-dir", default="backend/ml/artifacts/phase3")
    args = parser.parse_args()

    df = load_data(Path(args.input))
    output_dir = Path(args.output_dir)
    summary = train_suite(df, args.task, output_dir)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
