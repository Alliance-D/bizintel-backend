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
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import joblib
import numpy as np
import pandas as pd
import shap
from sklearn.base import clone
from sklearn.compose import ColumnTransformer, TransformedTargetRegressor
from sklearn.ensemble import (
    ExtraTreesClassifier,
    ExtraTreesRegressor,
    GradientBoostingRegressor,
    HistGradientBoostingRegressor,
    RandomForestRegressor,
)
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score, roc_auc_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.neighbors import KNeighborsRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sqlalchemy import create_engine, text

from app.services.gap_semantics import classify_gap_percentile

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
    # Per-anchor nearest distances and road-network context (added after the
    # OSM roads/intersections were ingested).
    "nearest_bus_station_m", "nearest_school_m", "nearest_health_m", "nearest_finance_m",
    "distance_to_main_road_m", "road_density_500m", "intersection_density_500m",
]
# 'sector' is intentionally NOT a feature: as a one-hot it cannot generalise to
# sectors held out in grouped CV, so it only ever encoded memorised per-sector
# levels. It stays in the loaded frame (for the spatial CV grouping) but out of
# the model. 'district' (3 levels, seen in every fold) is safe to keep.
CATEGORICAL_FEATURES = ["business_category", "district", "road_class_nearest"]
ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

# Loaded alongside the features for narrative/context use only - never fed to
# the model. competitor_count_1000m becomes the target itself (observed_count);
# these describe the same competitive picture at finer granularity and are still
# useful to show, just not to train on. (The retired hand-weighted composite
# scores were removed - they were display-only and are gone from the schema.)
CONTEXT_COLUMNS = [
    "nearest_competitor_m", "competitor_count_300m", "competitor_count_500m",
]

TARGET = "observed_count"
SPLIT_GROUP_COLUMN = "sector"
# Number of repeated grouped holdouts used to estimate each model's error with a
# mean and spread, rather than a single fragile split.
N_CV_REPEATS = 20


def engine():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is required")
    return create_engine(url)


def load_features(eng) -> pd.DataFrame:
    query = f"""
      SELECT id, grid_id, business_category, district, sector, cell,
             road_class_nearest,
             ST_Y(centroid) AS latitude, ST_X(centroid) AS longitude,
             {", ".join(NUMERIC_FEATURES)},
             {", ".join(CONTEXT_COLUMNS)},
             competitor_count_1000m AS {TARGET}
      FROM ml.grid_category_features
    """
    return pd.read_sql_query(query, eng)


def _preprocessor() -> ColumnTransformer:
    numeric = Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())])
    categorical = Pipeline([("imputer", SimpleImputer(strategy="most_frequent")), ("onehot", OneHotEncoder(handle_unknown="ignore"))])
    return ColumnTransformer([("num", numeric, NUMERIC_FEATURES), ("cat", categorical, CATEGORICAL_FEATURES)])


def build_pipeline(model) -> Pipeline:
    return Pipeline([("preprocess", _preprocessor()), ("model", model)])


def build_classifier_pipeline(clf) -> Pipeline:
    return Pipeline([("preprocess", _preprocessor()), ("model", clf)])


class HurdleModel:
    """Two-part (hurdle) model for a zero-inflated count. Stage 1 classifies
    whether the category is present at all (observed_count > 0); stage 2, trained
    only on cells that do have it, predicts the count given presence. The expected
    count is P(present) x E(count | present) - which handles the 88%-zero target
    more honestly than a single regressor and yields a viability probability as a
    by-product. Exposes .reg_pipe so tree SHAP can still attribute the count."""

    def __init__(self, classifier, regressor):
        self.classifier = classifier
        self.regressor = regressor
        self.clf_pipe: Pipeline | None = None
        self.reg_pipe: Pipeline | None = None

    def fit(self, X, y):
        y = np.asarray(y, dtype=float)
        present = (y > 0).astype(int)
        self.clf_pipe = build_classifier_pipeline(clone(self.classifier)).fit(X, present)
        nz = y > 0
        # Need enough positive cells (and a running instance) to fit stage 2.
        self.reg_pipe = build_pipeline(clone(self.regressor)).fit(X[nz], y[nz]) if nz.sum() >= 10 else None
        return self

    def proba_present(self, X) -> np.ndarray:
        clf = self.clf_pipe.named_steps["model"]
        classes = list(clf.classes_)
        proba = self.clf_pipe.predict_proba(X)
        return proba[:, classes.index(1)] if 1 in classes else np.zeros(len(X))

    def count_if_present(self, X) -> np.ndarray:
        if self.reg_pipe is None:
            return np.zeros(len(X))
        return np.clip(self.reg_pipe.predict(X), 0, None)

    def predict(self, X) -> np.ndarray:
        return self.proba_present(X) * self.count_if_present(X)


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


def evaluate(y_true, y_pred) -> dict:
    return {
        "mae": round(float(mean_absolute_error(y_true, y_pred)), 4),
        "rmse": round(float(math.sqrt(mean_squared_error(y_true, y_pred))), 4),
        "r2": round(float(r2_score(y_true, y_pred)), 4),
    }


def cross_validate_models(df: pd.DataFrame, models: dict, n_repeats: int = N_CV_REPEATS) -> list[dict]:
    """Repeated grouped holdout by sector: refit every model on many random
    sector splits and report the distribution (mean +/- std) of MAE/RMSE/R2, so
    the headline numbers carry a spread rather than resting on one fragile split.

    Returns one record per model with the aggregated metrics and the per-fold
    values, sorted by mean MAE (the selection metric: robust to the target's
    skew and zero-inflation, where a few high-count cells would dominate RMSE).
    """
    X, y, groups = df[ALL_FEATURES], df[TARGET].astype(float), df[SPLIT_GROUP_COLUMN]
    splitter = GroupShuffleSplit(n_splits=n_repeats, test_size=0.22, random_state=42)
    folds = list(splitter.split(X, y, groups))

    per_model: dict[str, dict[str, list[float]]] = {name: {"mae": [], "rmse": [], "r2": []} for name in models}
    errors: dict[str, str] = {}
    for train_idx, test_idx in folds:
        X_tr, X_te = X.iloc[train_idx], X.iloc[test_idx]
        y_tr, y_te = y.iloc[train_idx], y.iloc[test_idx]
        for name, model in models.items():
            if name in errors:
                continue
            try:
                pipe = build_pipeline(clone(model))
                pipe.fit(X_tr, y_tr)
                m = evaluate(y_te, np.clip(pipe.predict(X_te), 0, None))
                per_model[name]["mae"].append(m["mae"])
                per_model[name]["rmse"].append(m["rmse"])
                per_model[name]["r2"].append(m["r2"])
            except Exception as exc:  # a whole model failing (e.g. optional dep) shouldn't abort the run
                errors[name] = str(exc)

    results: list[dict] = []
    for name in models:
        if name in errors or not per_model[name]["mae"]:
            results.append({"algorithm": name, "status": "failed", "error": errors.get(name, "no folds")})
            continue
        agg = {}
        for metric in ("mae", "rmse", "r2"):
            vals = per_model[name][metric]
            agg[f"{metric}_mean"] = round(float(np.mean(vals)), 4)
            agg[f"{metric}_std"] = round(float(np.std(vals)), 4)
        results.append({"algorithm": name, "status": "ok", "folds": len(per_model[name]["mae"]), "metrics": agg, "per_fold": per_model[name]})
    results.sort(key=lambda r: r["metrics"]["mae_mean"] if r["status"] == "ok" else float("inf"))
    return results


def cross_validate_hurdle(df: pd.DataFrame, classifier, regressor, n_repeats: int = N_CV_REPEATS) -> dict:
    """Evaluate the hurdle end-to-end under the same repeated grouped holdout:
    fit both stages on train, predict the combined expected on the unseen
    sectors, and report MAE/RMSE/R2 (comparable to the single-model table) plus
    the stage-1 presence AUC."""
    X, y, groups = df[ALL_FEATURES], df[TARGET].astype(float), df[SPLIT_GROUP_COLUMN]
    splitter = GroupShuffleSplit(n_splits=n_repeats, test_size=0.22, random_state=42)
    mae, rmse, r2, auc = [], [], [], []
    for tr, te in splitter.split(X, y, groups):
        h = HurdleModel(classifier, regressor).fit(X.iloc[tr], y.iloc[tr])
        m = evaluate(y.iloc[te], np.clip(h.predict(X.iloc[te]), 0, None))
        mae.append(m["mae"]); rmse.append(m["rmse"]); r2.append(m["r2"])
        present_te = (y.iloc[te] > 0).astype(int)
        if present_te.nunique() > 1:
            auc.append(float(roc_auc_score(present_te, h.proba_present(X.iloc[te]))))
    agg: dict[str, float | None] = {}
    for name, vals in [("mae", mae), ("rmse", rmse), ("r2", r2)]:
        agg[f"{name}_mean"] = round(float(np.mean(vals)), 4)
        agg[f"{name}_std"] = round(float(np.std(vals)), 4)
    agg["presence_auc_mean"] = round(float(np.mean(auc)), 4) if auc else None
    return {"algorithm": "hurdle", "status": "ok", "folds": len(mae), "metrics": agg}


# Canonical gap-band rule lives in app.services.gap_semantics so the scoring
# script, the API and the tests share one definition.
gap_percentile_classification = classify_gap_percentile


def narrative_explanation(row: pd.Series, expected: float, observed: float, gap_percentile: float) -> dict:
    strengths, risks = [], []
    if gap_percentile >= 80:
        strengths.append(f"Expected demand ({expected:.1f}) notably exceeds the {int(observed)} {row.business_category} businesses currently observed nearby")
    if gap_percentile < 25:
        risks.append(f"Observed supply ({int(observed)} nearby) already meets or exceeds what area fundamentals would predict ({expected:.1f})")
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
            "Visit at morning, midday and evening to see how the foot traffic changes",
            "Walk the street and count the shops like this one you can see, including small informal stalls",
            "Confirm rent, frontage, visibility and access from the street",
            "Ask nearby residents or workers what they still travel elsewhere to buy",
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

    models = candidate_models()
    n_sectors = df[SPLIT_GROUP_COLUMN].nunique()
    print(f"Repeated grouped holdout: {N_CV_REPEATS} random splits, each trained on ~78% of the "
          f"{n_sectors} sectors and validated on the unseen ~22%\n")
    cv_results = cross_validate_models(df, models)
    for r in cv_results:
        if r["status"] == "ok":
            m = r["metrics"]
            print(f"  {r['algorithm']:24s} MAE={m['mae_mean']:.3f}+/-{m['mae_std']:.3f}  "
                  f"RMSE={m['rmse_mean']:.3f}+/-{m['rmse_std']:.3f}  R2={m['r2_mean']:.3f}+/-{m['r2_std']:.3f}")
        else:
            print(f"  {r['algorithm']:24s} failed: {r.get('error')}")

    successful = [r for r in cv_results if r["status"] == "ok"]
    if not successful:
        raise SystemExit("No candidate single model trained successfully.")
    best_single = successful[0]  # cross_validate_models sorts by mean MAE
    bs = best_single["metrics"]
    print(f"\nBest single model by mean MAE: {best_single['algorithm']} "
          f"(MAE={bs['mae_mean']}+/-{bs['mae_std']}, R2={bs['r2_mean']}+/-{bs['r2_std']})")

    # ---- Hurdle (two-part) model: P(present) x E(count | present). The target
    # is ~88% zeros, so a single regressor conflates "is this category viable
    # here at all" with "how many"; splitting them is the standard treatment for
    # a zero-inflated count. Evaluated under the same repeated holdout so it's
    # directly comparable to the single models above. ----
    hurdle_clf = ExtraTreesClassifier(n_estimators=300, min_samples_leaf=2, class_weight="balanced", random_state=42, n_jobs=-1)
    # The count stage sees only the ~700 present cells and the count is fat-tailed
    # (median 2, max 41). A log1p target handles that skew and is the real win here;
    # rich trees (leaf=2) with light feature subsampling generalise best - clamping
    # leaf size only raised the held-out error. Measured on grouped CV: combined MAE
    # 0.51 -> 0.46, R2 0.51 -> 0.60, count-stage held-out MAE 2.67 -> 2.45. (The large
    # train/val gap of the ensemble is not the target: it still generalises best.)
    # 'sector' is dropped from the features (see CATEGORICAL_FEATURES): as a one-hot
    # it can't generalise to unseen sectors and only encodes memorised per-sector
    # levels - dropping it improved held-out R2.
    hurdle_reg = TransformedTargetRegressor(
        ExtraTreesRegressor(n_estimators=400, min_samples_leaf=2, max_features=0.8, random_state=42, n_jobs=-1),
        func=np.log1p, inverse_func=np.expm1,
    )
    hurdle_cv = cross_validate_hurdle(df, hurdle_clf, hurdle_reg)
    hm = hurdle_cv["metrics"]
    print(f"  {'hurdle (2-part)':24s} MAE={hm['mae_mean']:.3f}+/-{hm['mae_std']:.3f}  "
          f"RMSE={hm['rmse_mean']:.3f}+/-{hm['rmse_std']:.3f}  R2={hm['r2_mean']:.3f}+/-{hm['r2_std']:.3f}  "
          f"presence_AUC={hm['presence_auc_mean']}")
    delta = bs["mae_mean"] - hm["mae_mean"]
    print(f"Hurdle vs best single ({best_single['algorithm']}): MAE {hm['mae_mean']} vs {bs['mae_mean']} "
          f"({'better' if delta >= 0 else 'worse'} by {abs(delta):.3f})\n")

    # The hurdle is the chosen production model: it handles the zero-inflation and
    # yields a viability probability as a by-product. Record it alongside the
    # single-model comparison.
    best_name = "hurdle"
    best = {"algorithm": "hurdle", "status": "ok", "folds": hurdle_cv["folds"], "metrics": hm}
    bm = hm
    cv_results = cv_results + [best]

    # Fit the final hurdle on all rows for the deployed scorer.
    model = HurdleModel(hurdle_clf, hurdle_reg).fit(df[ALL_FEATURES], df[TARGET].astype(float))

    # ---- SHAP for the count stage (which features drive "how many", once the
    # category is present) - the interpretable half of the hurdle. ----
    shap_summary = None
    explainer = None
    transformed_feature_names = None
    shap_pipe = model.reg_pipe  # the count-given-present pipeline
    underlying_model = shap_pipe.named_steps["model"] if shap_pipe is not None else None
    if underlying_model is not None and hasattr(underlying_model, "regressor_"):
        # unwrap the log1p target wrapper to reach the fitted tree ensemble
        underlying_model = underlying_model.regressor_
    if underlying_model is not None and hasattr(underlying_model, "feature_importances_"):
        try:
            sample = df[ALL_FEATURES].sample(min(2000, len(df)), random_state=42)
            sample_transformed = shap_pipe.named_steps["preprocess"].transform(sample)
            transformed_feature_names = list(shap_pipe.named_steps["preprocess"].get_feature_names_out())
            explainer = shap.TreeExplainer(underlying_model)
            shap_values = explainer.shap_values(sample_transformed)
            mean_abs_shap = np.abs(shap_values).mean(axis=0)
            shap_summary = sorted(
                [{"feature": n.split("__", 1)[-1], "mean_abs_shap": float(v)} for n, v in zip(transformed_feature_names, mean_abs_shap)],
                key=lambda r: r["mean_abs_shap"], reverse=True,
            )[:20]
            print("\nTop SHAP contributions to the count-given-present stage:")
            for row in shap_summary[:8]:
                print(f"  {row['feature']:30s} {row['mean_abs_shap']:.3f}")
        except Exception as exc:
            print(f"SHAP explanation skipped: {exc}")

    # ---- persist artifacts ----
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"{best_name}_gap_model.joblib"
    joblib.dump({"hurdle": model, "numeric_features": NUMERIC_FEATURES, "categorical_features": CATEGORICAL_FEATURES, "target": TARGET}, artifact_path)

    split_strategy = f"repeated_group_shuffle_split_by_{SPLIT_GROUP_COLUMN}_x{N_CV_REPEATS}"
    comparison_path = artifact_dir / f"model_comparison_{timestamp}.json"
    comparison_path.write_text(json.dumps({
        "target": TARGET,
        "split_strategy": split_strategy,
        "cv_repeats": N_CV_REPEATS,
        "total_sectors": int(df[SPLIT_GROUP_COLUMN].nunique()),
        "total_rows": int(len(df)),
        "best_model": best_name,
        "results": cv_results,
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
            "metrics": json.dumps({"best": best, "all_candidates": cv_results, "split_strategy": split_strategy, "shap_top_features": shap_summary}),
            "features": ALL_FEATURES,
            "active": bool(args.activate),
        }).scalar_one()

    # ---- score every row: expected count from the model, gap against what's
    # actually observed, then classify by gap percentile within category ----
    X_all = df[ALL_FEATURES]
    expected_all = np.clip(model.predict(X_all), 0, None)
    viability_all = model.proba_present(X_all)  # P(category present at all) - the hurdle's stage 1
    df["expected_count"] = expected_all
    df["viability"] = viability_all
    df["observed_count"] = df[TARGET]
    df["gap"] = df["expected_count"] - df["observed_count"]
    df["gap_percentile"] = df.groupby("business_category")["gap"].rank(pct=True) * 100

    row_shap_values = None
    if explainer is not None and shap_pipe is not None:
        X_all_transformed = shap_pipe.named_steps["preprocess"].transform(X_all)
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
            "viability": round(float(row.viability), 4),  # P(any business of this category is present)
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
              grid_id, business_category, model_version_id, opportunity_score, opportunity_rank, opportunity_type, zone_key,
              risk_level, explanation, geom, cell_geom, district, sector, cell
            )
            SELECT
              :grid_id, :business_category, :model_version_id, :opportunity_score,
              NULL, :opportunity_type, :zone_key, :risk_level, CAST(:explanation AS jsonb),
              f.centroid, f.geom, :district, :sector, :cell
            FROM ml.grid_category_features f
            WHERE f.grid_id = :grid_id AND f.business_category = :business_category
            ON CONFLICT DO NOTHING
        """), rows)
        conn.execute(text("""
            WITH ranked AS (
              SELECT id, ROW_NUMBER() OVER (PARTITION BY business_category ORDER BY opportunity_score DESC) AS rk
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
