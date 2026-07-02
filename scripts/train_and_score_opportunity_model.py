"""Train, compare, and score the opportunity/suitability index model.

This is a decision-support index, not a business-success or revenue
predictor. The target (opportunity_gap_score) is a documented, transparent
weighted composite of demand, accessibility, commercial activity, inverse
competition, and welfare (see app/db/schema.py's meta.feature_catalog seed
and build_grid_category_features.py). What this script adds is a model that
learns a smoothed, spatially-generalizable version of that composite, so it
can score any candidate location rather than only the exact grid cells the
composite was computed for - evaluated honestly with a spatial holdout
(trained on some sectors, tested on sectors the model never saw).

Steps:
    1. Load ml.grid_category_features from PostGIS.
    2. Split by sector (not randomly) so validation measures generalization
       to unseen areas, not memorization of nearby cells.
    3. Train and compare several model families.
    4. Pick the best by validation MAE, compute SHAP explanations for it.
    5. Save the artifact, feature schema, comparison table and SHAP summary.
    6. Register the model version and score every grid cell/category row,
       writing ranked predictions with a real explanation into
       ml.ml_opportunity_predictions.
    7. Report how predictions compare to any collected field validation
       observations, as a calibration check (not additional training data).

Usage:
    python scripts/train_and_score_opportunity_model.py --activate
"""
from __future__ import annotations

import argparse
import json
import math
import os
import warnings
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import shap
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (
    ExtraTreesRegressor,
    GradientBoostingRegressor,
    HistGradientBoostingRegressor,
    RandomForestRegressor,
)
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.neighbors import KNeighborsRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sqlalchemy import create_engine, text

warnings.filterwarnings("ignore", category=UserWarning)

try:
    from lightgbm import LGBMRegressor
except ImportError:  # pragma: no cover
    LGBMRegressor = None

try:
    from xgboost import XGBRegressor
except ImportError:  # pragma: no cover
    XGBRegressor = None

NUMERIC_FEATURES = [
    "population_density_500m", "population_density_1000m", "sector_population",
    "employment_rate", "income_proxy", "welfare_proxy",
    "competitor_count_300m", "competitor_count_500m", "competitor_count_1000m", "nearest_competitor_m",
    "complementary_poi_count_500m", "commercial_poi_count_500m", "demand_generator_count_1000m",
    "market_distance_m", "school_count_1000m", "health_facility_count_1000m",
    "bus_stop_count_500m", "nearest_bus_stop_m", "establishment_category_count_area",
    "demand_score", "accessibility_score", "commercial_activity_score", "competition_pressure",
    "welfare_score", "confidence_score",
]
CATEGORICAL_FEATURES = ["business_category", "district", "sector"]
ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
TARGET = "opportunity_gap_score"
SPLIT_GROUP_COLUMN = "sector"


def engine():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is required")
    return create_engine(url)


def load_features(eng) -> pd.DataFrame:
    query = f"""
      SELECT id, grid_id, business_category, district, sector, cell,
             ST_Y(centroid) AS latitude, ST_X(centroid) AS longitude,
             {", ".join(NUMERIC_FEATURES)},
             {TARGET}
      FROM ml.grid_category_features
    """
    return pd.read_sql_query(query, eng)


def build_pipeline(model) -> Pipeline:
    numeric = Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())])
    categorical = Pipeline([("imputer", SimpleImputer(strategy="most_frequent")), ("onehot", OneHotEncoder(handle_unknown="ignore"))])
    pre = ColumnTransformer([("num", numeric, NUMERIC_FEATURES), ("cat", categorical, CATEGORICAL_FEATURES)])
    return Pipeline([("preprocess", pre), ("model", model)])


def candidate_models() -> dict:
    models = {
        "random_forest": RandomForestRegressor(n_estimators=250, min_samples_leaf=3, random_state=42, n_jobs=-1),
        "extra_trees": ExtraTreesRegressor(n_estimators=300, min_samples_leaf=2, random_state=42, n_jobs=-1),
        "gradient_boosting": GradientBoostingRegressor(random_state=42),
        "hist_gradient_boosting": HistGradientBoostingRegressor(random_state=42, max_iter=250, learning_rate=0.06),
        "k_nearest_neighbors": KNeighborsRegressor(n_neighbors=15, weights="distance"),
    }
    if LGBMRegressor:
        models["lightgbm"] = LGBMRegressor(n_estimators=400, learning_rate=0.04, num_leaves=31, random_state=42, verbosity=-1)
    if XGBRegressor:
        models["xgboost"] = XGBRegressor(n_estimators=350, learning_rate=0.04, max_depth=5, subsample=0.85, colsample_bytree=0.85, random_state=42)
    return models


def spatial_split(df: pd.DataFrame):
    """Group-based holdout by sector: the model is validated on sectors it never trained on."""
    groups = df[SPLIT_GROUP_COLUMN]
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.22, random_state=42)
    train_idx, test_idx = next(splitter.split(df, df[TARGET], groups=groups))
    train_df, test_df = df.iloc[train_idx].copy(), df.iloc[test_idx].copy()
    overlap = set(train_df[SPLIT_GROUP_COLUMN]) & set(test_df[SPLIT_GROUP_COLUMN])
    assert not overlap, f"Spatial holdout leaked sectors across the split: {overlap}"
    return train_df, test_df


def evaluate(y_true, y_pred) -> dict:
    return {
        "mae": round(float(mean_absolute_error(y_true, y_pred)), 4),
        "rmse": round(float(math.sqrt(mean_squared_error(y_true, y_pred))), 4),
        "r2": round(float(r2_score(y_true, y_pred)), 4),
    }


def opportunity_type(score: float, competition: float) -> tuple[str, str, str]:
    if score >= 80 and competition < 65:
        return "Strong opportunity", "strong", "low"
    if score >= 70 and competition < 60:
        return "Underserved opportunity", "underserved", "low"
    if score >= 68 and competition >= 65:
        return "High demand and high competition", "crowded", "high"
    if score >= 55:
        return "Promising but needs validation", "emerging", "medium"
    return "Low priority", "low", "medium"


def narrative_explanation(row: pd.Series, score: float) -> dict:
    strengths, risks = [], []
    if row.demand_score >= 70:
        strengths.append("Demand signal is strong from population and household concentration")
    if row.accessibility_score >= 70:
        strengths.append("Access is favourable from transport or road proximity")
    if row.commercial_activity_score >= 65:
        strengths.append("Commercial activity nearby can support customer flow")
    if row.competition_pressure >= 70:
        risks.append("Competition pressure is high and differentiation should be checked")
    if row.confidence_score < 55:
        risks.append("Data confidence is limited and field validation is important")
    if row.nearest_competitor_m and row.nearest_competitor_m < 200:
        risks.append("A similar business appears close to this grid cell")
    if not strengths:
        strengths.append("The location has moderate signals and should be compared with stronger cells")
    return {
        "summary": f"This location scores {round(score)}/100 for {row.business_category} as a spatial opportunity index. It is a decision-support signal, not a prediction of revenue or business success.",
        "strengths": strengths,
        "risks": risks,
        "field_checks": [
            "Count visible competitors and informal businesses nearby",
            "Check foot traffic during morning, midday and evening",
            "Confirm rent, frontage, visibility and access from the street",
            "Ask nearby residents or workers about unmet needs and price expectations",
        ],
    }


def collapse_shap_to_source_features(shap_row: np.ndarray, transformed_names: list[str]) -> dict[str, float]:
    """One-hot columns (e.g. district_Gasabo, district_Kicukiro) are summed back
    into their original feature (district) so explanations read naturally."""
    collapsed: dict[str, float] = {}
    for value, name in zip(shap_row, transformed_names):
        source = name.split("__", 1)[-1]
        for cat_col in CATEGORICAL_FEATURES:
            if source.startswith(f"{cat_col}_"):
                source = cat_col
                break
        collapsed[source] = collapsed.get(source, 0.0) + float(value)
    return collapsed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--artifact-dir", default="ml/artifacts")
    args = parser.parse_args()

    eng = engine()
    df = load_features(eng)
    if len(df) < 50:
        raise SystemExit(f"Not enough feature rows to train. Found {len(df)} rows. Generate grid and features first")

    train_df, test_df = spatial_split(df)
    X_train, y_train = train_df[ALL_FEATURES], train_df[TARGET].astype(float)
    X_test, y_test = test_df[ALL_FEATURES], test_df[TARGET].astype(float)

    results = []
    fitted = {}
    print(f"Training on {len(train_df):,} rows ({train_df[SPLIT_GROUP_COLUMN].nunique()} sectors), "
          f"validating on {len(test_df):,} rows ({test_df[SPLIT_GROUP_COLUMN].nunique()} unseen sectors)\n")
    for name, model in candidate_models().items():
        try:
            pipe = build_pipeline(model)
            pipe.fit(X_train, y_train)
            pred = np.clip(pipe.predict(X_test), 0, 100)
            metrics = evaluate(y_test, pred)
            results.append({"algorithm": name, "metrics": metrics, "status": "ok"})
            fitted[name] = pipe
            print(f"  {name:24s} MAE={metrics['mae']:6.2f}  RMSE={metrics['rmse']:6.2f}  R2={metrics['r2']:6.3f}")
        except Exception as exc:
            results.append({"algorithm": name, "metrics": {}, "status": "failed", "error": str(exc)})
            print(f"  {name:24s} failed: {exc}")

    successful = [r for r in results if r["status"] == "ok"]
    if not successful:
        raise SystemExit("No candidate model trained successfully.")
    best = sorted(successful, key=lambda r: r["metrics"]["mae"])[0]
    best_name = best["algorithm"]
    model = fitted[best_name]
    print(f"\nBest model: {best_name} (MAE={best['metrics']['mae']})")

    # ---- SHAP explanations for the winning model (tree-based models only;
    # KNeighborsRegressor and other non-tree models fall back gracefully) ----
    shap_summary = None
    explainer = None
    transformed_feature_names = None
    underlying_model = model.named_steps["model"]
    if hasattr(underlying_model, "feature_importances_") or type(underlying_model).__name__ in {
        "RandomForestRegressor", "ExtraTreesRegressor", "GradientBoostingRegressor",
        "HistGradientBoostingRegressor", "LGBMRegressor", "XGBRegressor",
    }:
        try:
            X_test_transformed = model.named_steps["preprocess"].transform(X_test)
            transformed_feature_names = list(model.named_steps["preprocess"].get_feature_names_out())
            explainer = shap.TreeExplainer(underlying_model)
            shap_values = explainer.shap_values(X_test_transformed)
            mean_abs_shap = np.abs(shap_values).mean(axis=0)
            shap_summary = sorted(
                [{"feature": n.split("__", 1)[-1], "mean_abs_shap": float(v)} for n, v in zip(transformed_feature_names, mean_abs_shap)],
                key=lambda r: r["mean_abs_shap"], reverse=True,
            )[:20]
            print("\nTop SHAP feature contributions (validation set):")
            for row in shap_summary[:8]:
                print(f"  {row['feature']:30s} {row['mean_abs_shap']:.3f}")
        except Exception as exc:
            print(f"SHAP explanation skipped: {exc}")

    # ---- persist artifacts ----
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"{best_name}_opportunity_model.joblib"
    joblib.dump({"pipeline": model, "numeric_features": NUMERIC_FEATURES, "categorical_features": CATEGORICAL_FEATURES, "target": TARGET}, artifact_path)

    comparison_path = artifact_dir / f"model_comparison_{timestamp}.json"
    comparison_path.write_text(json.dumps({
        "target": TARGET,
        "split_strategy": f"group_shuffle_split_by_{SPLIT_GROUP_COLUMN}",
        "training_rows": int(len(train_df)),
        "training_sectors": int(train_df[SPLIT_GROUP_COLUMN].nunique()),
        "validation_rows": int(len(test_df)),
        "validation_sectors": int(test_df[SPLIT_GROUP_COLUMN].nunique()),
        "best_model": best_name,
        "results": results,
        "shap_top_features": shap_summary,
    }, indent=2), encoding="utf-8")
    print(f"\nWrote model comparison: {comparison_path}")

    # ---- register model version ----
    with eng.begin() as conn:
        if args.activate:
            deactivated_ids = conn.execute(text(
                "UPDATE ml.model_versions SET is_active = FALSE WHERE business_category IS NULL AND target_name = :target RETURNING id"
            ), {"target": TARGET}).scalars().all()
            if deactivated_ids:
                # Keep the predictions table scoped to the currently active model;
                # comparison metrics for prior versions stay in ml.model_versions.metrics.
                conn.execute(text("DELETE FROM ml.ml_opportunity_predictions WHERE model_version_id = ANY(:ids)"), {"ids": deactivated_ids})
        version_id = conn.execute(text("""
            INSERT INTO ml.model_versions (model_name, business_category, target_name, algorithm, artifact_path, metrics, feature_columns, is_active, activated_at)
            VALUES ('opportunity_index_model', NULL, :target, :algorithm, :artifact_path, CAST(:metrics AS jsonb), :features, :active, CASE WHEN :active THEN now() ELSE NULL END)
            RETURNING id
        """), {
            "target": TARGET,
            "algorithm": best_name,
            "artifact_path": str(artifact_path),
            "metrics": json.dumps({"best": best, "all_candidates": results, "split_strategy": f"group_shuffle_split_by_{SPLIT_GROUP_COLUMN}", "shap_top_features": shap_summary}),
            "features": ALL_FEATURES,
            "active": bool(args.activate),
        }).scalar_one()

    # ---- score every row and write ranked predictions with real explanations ----
    X_all = df[ALL_FEATURES]
    all_pred = np.clip(model.predict(X_all), 0, 100)
    df["predicted_score"] = all_pred

    row_shap_values = None
    if explainer is not None:
        X_all_transformed = model.named_steps["preprocess"].transform(X_all)
        row_shap_values = explainer.shap_values(X_all_transformed)

    rows = []
    for i, (_, row) in enumerate(df.iterrows()):
        opp_type, zone_key, risk = opportunity_type(float(row.predicted_score), float(row.competition_pressure or 0))
        explanation = narrative_explanation(row, float(row.predicted_score))
        if row_shap_values is not None:
            top_factors = collapse_shap_to_source_features(row_shap_values[i], transformed_feature_names)
            top_factors_sorted = sorted(top_factors.items(), key=lambda kv: abs(kv[1]), reverse=True)[:6]
            explanation["shap_factors"] = [
                {"feature": name, "contribution": round(value, 3), "direction": "increases" if value > 0 else "decreases"}
                for name, value in top_factors_sorted
            ]
        rows.append({
            "grid_id": row.grid_id,
            "business_category": row.business_category,
            "model_version_id": version_id,
            "opportunity_score": float(row.predicted_score),
            "demand_score": float(row.demand_score or 0),
            "accessibility_score": float(row.accessibility_score or 0),
            "commercial_activity_score": float(row.commercial_activity_score or 0),
            "competition_pressure": float(row.competition_pressure or 0),
            "confidence_score": float(row.confidence_score or 0),
            "opportunity_type": opp_type,
            "zone_key": zone_key,
            "risk_level": risk,
            "explanation": json.dumps(explanation),
            "district": row.district,
            "sector": row.sector,
            "cell": row.cell,
        })

    with eng.begin() as conn:
        conn.execute(text("DELETE FROM ml.ml_opportunity_predictions WHERE model_version_id = :version_id"), {"version_id": version_id})
        conn.execute(text("""
            INSERT INTO ml.ml_opportunity_predictions (
              grid_id, business_category, model_version_id, opportunity_score, demand_score, accessibility_score,
              commercial_activity_score, competition_pressure, confidence_score, opportunity_rank, opportunity_type, zone_key,
              risk_level, explanation, geom, cell_geom, district, sector, cell
            )
            SELECT
              :grid_id, :business_category, :model_version_id, :opportunity_score, :demand_score, :accessibility_score,
              :commercial_activity_score, :competition_pressure, :confidence_score,
              NULL, :opportunity_type, :zone_key, :risk_level, CAST(:explanation AS jsonb),
              f.centroid, f.geom, :district, :sector, :cell
            FROM ml.grid_category_features f
            WHERE f.grid_id = :grid_id AND f.business_category = :business_category
            ON CONFLICT DO NOTHING
        """), rows)
        conn.execute(text("""
            WITH ranked AS (
              SELECT id, ROW_NUMBER() OVER (PARTITION BY business_category ORDER BY opportunity_score DESC, confidence_score DESC) AS rk
              FROM ml.ml_opportunity_predictions WHERE model_version_id = :version_id
            )
            UPDATE ml.ml_opportunity_predictions p SET opportunity_rank = r.rk FROM ranked r WHERE p.id = r.id
        """), {"version_id": version_id})

    print(f"\n{'Activated' if args.activate else 'Trained'} model version {version_id} using {best_name}")
    print(f"Wrote {len(rows):,} predictions")

    # ---- field validation calibration check (informational, not additional training data) ----
    with eng.connect() as conn:
        validation_count = conn.execute(text("SELECT COUNT(*) FROM field.validation_points")).scalar_one()
    if validation_count == 0:
        print("\nField validation calibration: no field observations collected yet.")
    else:
        print(f"\nField validation calibration: {validation_count} observations available "
              f"(see scripts/calibrate_against_field_validation.py once field data collection begins).")


if __name__ == "__main__":
    main()
