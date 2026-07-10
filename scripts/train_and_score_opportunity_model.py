"""Train, compare, and score the demand-vs-supply gap model.

This predicts observed business presence, not a hand-weighted composite and
not business success. For a business category, the target is how many of
that category's businesses are actually observed within 1km of a grid cell
(observed_count, real OSM-derived data). The model learns to predict that
count from area fundamentals alone - population, income, transport, and
category-agnostic anchors - with the category's own current presence
deliberately excluded from the inputs. Feed a model its own answer and it
just reads it back; that was the flaw in the previous composite-index
target, which was built from the same sub-scores used as its own features
(hence a suspicious 0.994 validation R2 - the model was reconstructing
arithmetic it had already been given, not predicting anything).

The gap (expected_count - observed_count) is the real finding:
  gap > 0  -> underserved, expected demand outstrips what's actually there
  gap ~ 0  -> balanced
  gap < 0  -> saturated, more supply than the fundamentals would predict

This does not promise business success and cannot see businesses OSM never
mapped (informal shops in particular) - it measures a spatial mismatch
between demand-side fundamentals and observed supply, nothing more.

Steps:
    1. Load ml.grid_category_features from PostGIS.
    2. Split by sector (not randomly) so validation measures generalization
       to unseen areas, not memorization of nearby cells.
    3. Train and compare several model families predicting observed_count.
    4. Pick the best by validation MAE, compute SHAP explanations for it.
    5. Save the artifact, feature schema, comparison table and SHAP summary.
    6. Score every grid cell/category row, classify by gap percentile within
       its category, and write ranked predictions with a real explanation
       into ml.ml_opportunity_predictions.
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

# Fundamentals only - deliberately excludes the category's own current
# presence (competitor_count_*, nearest_competitor_m,
# establishment_category_count_area, competition_pressure all leak the
# target directly or near-directly) and confidence_score, whose formula in
# build_grid_category_features.py includes a term for
# "competitor_count_1000m > 0", a partial leak of the target's sign.
#
# demand_score/accessibility_score/commercial_activity_score/welfare_score
# are deliberately excluded too: they're hand-weighted formulas computed
# from the raw fundamentals already listed below (welfare_score is a literal
# copy of welfare_proxy), so including both would feed the model the same
# signal twice - once raw, once pre-aggregated - and let a hand-tuned
# formula quietly re-enter a model that's supposed to learn its own
# relationships from the raw counts/distances directly.
NUMERIC_FEATURES = [
    "population_density_500m", "population_density_1000m", "sector_population",
    "employment_rate", "income_proxy", "welfare_proxy",
    "complementary_poi_count_500m", "commercial_poi_count_500m", "demand_generator_count_1000m",
    "market_distance_m", "school_count_1000m", "health_facility_count_1000m",
    "bus_stop_count_500m", "nearest_bus_stop_m",
]
CATEGORICAL_FEATURES = ["business_category", "district", "sector"]
ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

# Loaded alongside the features for narrative/context use only - never fed
# to the model. competitor_count_1000m becomes the target itself
# (observed_count); the others describe the same competitive picture at
# finer/different granularity and are still useful to show, just not to
# train on. The four hand-weighted composite scores are kept here too, for
# display/backward-compat only.
CONTEXT_COLUMNS = [
    "confidence_score", "competition_pressure", "nearest_competitor_m",
    "competitor_count_300m", "competitor_count_500m",
    "demand_score", "accessibility_score", "commercial_activity_score", "welfare_score",
]

TARGET = "observed_count"
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
             {", ".join(CONTEXT_COLUMNS)},
             competitor_count_1000m AS {TARGET}
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


def gap_percentile_classification(gap_percentile: float) -> tuple[str, str, str]:
    """gap_percentile is this row's rank (0-100) among gap values within its
    own business_category - relative, not an absolute magnitude, so it's
    comparable across categories with very different typical counts."""
    if gap_percentile >= 80:
        return "Underserved", "underserved", "low"
    if gap_percentile >= 55:
        return "Room to grow", "emerging", "medium"
    if gap_percentile >= 25:
        return "Balanced", "balanced", "medium"
    return "Saturated", "saturated", "high"


def narrative_explanation(row: pd.Series, expected: float, observed: float, gap_percentile: float) -> dict:
    strengths, risks = [], []
    if row.demand_score >= 70:
        strengths.append("Demand signal is strong from population and household concentration")
    if row.accessibility_score >= 70:
        strengths.append("Access is favourable from transport or road proximity")
    if gap_percentile >= 80:
        strengths.append(f"Expected demand ({expected:.1f}) notably exceeds the {int(observed)} {row.business_category} businesses currently observed nearby")
    if gap_percentile < 25:
        risks.append(f"Observed supply ({int(observed)} nearby) already meets or exceeds what area fundamentals would predict ({expected:.1f})")
    if row.confidence_score < 55:
        risks.append("Data confidence is limited and field validation is important")
    if not strengths:
        strengths.append("The location has moderate signals and should be compared with stronger cells")
    return {
        "summary": (
            f"For {row.business_category}, area fundamentals predict about {expected:.1f} businesses nearby; "
            f"{int(observed)} are actually observed. This is a demand-versus-supply gap signal, not a "
            f"prediction of revenue or business success, and it can't see businesses OSM never mapped."
        ),
        "strengths": strengths,
        "risks": risks,
        "field_checks": [
            "Count visible competitors and informal businesses nearby - OSM undercounts these",
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

    print(f"Target ({TARGET}) distribution: min={df[TARGET].min():.0f} max={df[TARGET].max():.0f} "
          f"mean={df[TARGET].mean():.2f} zeros={(df[TARGET] == 0).mean():.1%}\n")

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
            pred = np.clip(pipe.predict(X_test), 0, None)
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
    print(f"\nBest model: {best_name} (MAE={best['metrics']['mae']}, R2={best['metrics']['r2']})")
    if best["metrics"]["r2"] > 0.9:
        print("NOTE: R2 above 0.9 for a genuine observed-count target would be surprising - "
              "double check NUMERIC_FEATURES doesn't still contain something that leaks the target.")

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
    artifact_path = artifact_dir / f"{best_name}_gap_model.joblib"
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
            # Deactivate whatever was active before, regardless of its target_name -
            # there should only ever be one active model in this global (non-per-category)
            # slot, even across a target rename like the Path B migration.
            deactivated_ids = conn.execute(text(
                "UPDATE ml.model_versions SET is_active = FALSE WHERE business_category IS NULL AND is_active = TRUE RETURNING id"
            )).scalars().all()
            if deactivated_ids:
                # Keep the predictions table scoped to the currently active model;
                # comparison metrics for prior versions stay in ml.model_versions.metrics.
                conn.execute(text("DELETE FROM ml.ml_opportunity_predictions WHERE model_version_id = ANY(:ids)"), {"ids": deactivated_ids})
        version_id = conn.execute(text("""
            INSERT INTO ml.model_versions (model_name, business_category, target_name, algorithm, artifact_path, metrics, feature_columns, is_active, activated_at)
            VALUES ('demand_supply_gap_model', NULL, :target, :algorithm, :artifact_path, CAST(:metrics AS jsonb), :features, :active, CASE WHEN :active THEN now() ELSE NULL END)
            RETURNING id
        """), {
            "target": TARGET,
            "algorithm": best_name,
            "artifact_path": artifact_path.as_posix(),
            "metrics": json.dumps({"best": best, "all_candidates": results, "split_strategy": f"group_shuffle_split_by_{SPLIT_GROUP_COLUMN}", "shap_top_features": shap_summary}),
            "features": ALL_FEATURES,
            "active": bool(args.activate),
        }).scalar_one()

    # ---- score every row: expected count from the model, gap against what's
    # actually observed, then classify by gap percentile within category ----
    X_all = df[ALL_FEATURES]
    expected_all = np.clip(model.predict(X_all), 0, None)
    df["expected_count"] = expected_all
    df["observed_count"] = df[TARGET]
    df["gap"] = df["expected_count"] - df["observed_count"]
    df["gap_percentile"] = df.groupby("business_category")["gap"].rank(pct=True) * 100

    row_shap_values = None
    if explainer is not None:
        X_all_transformed = model.named_steps["preprocess"].transform(X_all)
        row_shap_values = explainer.shap_values(X_all_transformed)

    rows = []
    for i, (_, row) in enumerate(df.iterrows()):
        opp_type, zone_key, risk = gap_percentile_classification(float(row.gap_percentile))
        explanation = narrative_explanation(row, float(row.expected_count), float(row.observed_count), float(row.gap_percentile))
        explanation["gap_details"] = {
            "expected_count": round(float(row.expected_count), 3),
            "observed_count": float(row.observed_count),
            "gap": round(float(row.gap), 3),
            "gap_percentile_within_category": round(float(row.gap_percentile), 1),
        }
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
            # opportunity_score keeps its existing column/name (no schema
            # migration in this pass) but now honestly holds the gap
            # percentile within category - 100 = most underserved relative
            # to peers, 0 = most saturated. Raw expected/observed/gap live
            # in explanation.gap_details for anything that wants the
            # unrounded numbers.
            "opportunity_score": float(row.gap_percentile),
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
    print("\nGap classification counts:")
    print(df.groupby("business_category").apply(
        lambda g: pd.Series({
            "underserved": (g["gap_percentile"] >= 80).sum(),
            "room_to_grow": ((g["gap_percentile"] >= 55) & (g["gap_percentile"] < 80)).sum(),
            "balanced": ((g["gap_percentile"] >= 25) & (g["gap_percentile"] < 55)).sum(),
            "saturated": (g["gap_percentile"] < 25).sum(),
        }), include_groups=False,
    ))

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
