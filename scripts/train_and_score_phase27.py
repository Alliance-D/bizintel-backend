"""Train and compare ML models, then write scored grid predictions.

This is the first real ML bridge for BizIntel. It trains on the objective
opportunity-gap proxy created from real spatial features. Later, field validation
can be used to calibrate the target, but field notes should not replace the
core public-data training matrix.

Example:
    python scripts/train_and_score_phase27.py --activate
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
from sklearn.ensemble import ExtraTreesRegressor, GradientBoostingRegressor, HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score, mean_squared_error
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.impute import SimpleImputer

NUMERIC_FEATURES = [
    "population_density_500m", "population_density_1000m", "sector_population",
    "employment_rate", "income_proxy", "welfare_proxy",
    "competitor_count_300m", "competitor_count_500m", "competitor_count_1000m", "nearest_competitor_m",
    "complementary_poi_count_500m", "commercial_poi_count_500m", "demand_generator_count_1000m",
    "market_distance_m", "school_count_1000m", "health_facility_count_1000m",
    "bus_stop_count_500m", "nearest_bus_stop_m", "establishment_category_count_area",
    "demand_score", "accessibility_score", "commercial_activity_score", "competition_pressure", "welfare_score", "confidence_score",
]
CATEGORICAL_FEATURES = ["business_category", "district", "sector"]
TARGET = "opportunity_gap_score"


def engine():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is required")
    return create_engine(url)


def load_features(eng) -> pd.DataFrame:
    query = """
      SELECT id, grid_id, business_category, district, sector, cell,
             ST_Y(centroid) AS latitude, ST_X(centroid) AS longitude,
             population_density_500m, population_density_1000m, sector_population,
             employment_rate, income_proxy, welfare_proxy,
             competitor_count_300m, competitor_count_500m, competitor_count_1000m, nearest_competitor_m,
             complementary_poi_count_500m, commercial_poi_count_500m, demand_generator_count_1000m,
             market_distance_m, school_count_1000m, health_facility_count_1000m,
             bus_stop_count_500m, nearest_bus_stop_m, establishment_category_count_area,
             demand_score, accessibility_score, commercial_activity_score, competition_pressure, welfare_score, confidence_score,
             opportunity_gap_score
      FROM ml.grid_category_features
    """
    return pd.read_sql_query(query, eng)


def build_pipeline(model):
    numeric = Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())])
    categorical = Pipeline([("imputer", SimpleImputer(strategy="most_frequent")), ("onehot", OneHotEncoder(handle_unknown="ignore"))])
    pre = ColumnTransformer([("num", numeric, NUMERIC_FEATURES), ("cat", categorical, CATEGORICAL_FEATURES)])
    return Pipeline([("preprocess", pre), ("model", model)])


def model_suite():
    return {
        "random_forest": RandomForestRegressor(n_estimators=220, random_state=42, min_samples_leaf=3, n_jobs=-1),
        "extra_trees": ExtraTreesRegressor(n_estimators=240, random_state=42, min_samples_leaf=2, n_jobs=-1),
        "gradient_boosting": GradientBoostingRegressor(random_state=42),
        "hist_gradient_boosting": HistGradientBoostingRegressor(random_state=42, max_iter=200),
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


def explanation(row: pd.Series, score: float) -> dict:
    strengths = []
    risks = []
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
        "summary": f"This grid cell scores {round(score)} for {row.business_category}. Use it for shortlisting, not as a guarantee",
        "strengths": strengths,
        "risks": risks,
        "lens_details": {
            "demand": {
                "population_density_500m": float(row.population_density_500m or 0),
                "sector_population": float(row.sector_population or 0),
                "interpretation": "Higher residential and household concentration increases everyday demand",
            },
            "competition": {
                "within_300m": int(row.competitor_count_300m or 0),
                "within_500m": int(row.competitor_count_500m or 0),
                "within_1000m": int(row.competitor_count_1000m or 0),
                "nearest_competitor_m": float(row.nearest_competitor_m or 0),
            },
            "access": {
                "bus_stops_500m": int(row.bus_stop_count_500m or 0),
                "nearest_bus_stop_m": float(row.nearest_bus_stop_m or 0),
            },
            "activity": {
                "commercial_pois_500m": int(row.commercial_poi_count_500m or 0),
                "demand_generators_1000m": int(row.demand_generator_count_1000m or 0),
            },
            "confidence": {
                "score": float(row.confidence_score or 0),
                "interpretation": "Confidence improves when population, OSM, POI and sector signals are available",
            },
        },
        "field_checks": [
            "Count visible competitors and informal businesses nearby",
            "Check foot traffic during morning, midday and evening",
            "Confirm rent, frontage, visibility and access from the street",
            "Ask nearby residents or workers about unmet needs and price expectations",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--artifact-dir", default="backend/ml/artifacts/phase27")
    args = parser.parse_args()
    eng = engine()
    df = load_features(eng)
    if len(df) < 50:
        raise SystemExit(f"Not enough feature rows to train. Found {len(df)} rows. Generate grid and features first")
    X = df[NUMERIC_FEATURES + CATEGORICAL_FEATURES]
    y = df[TARGET].astype(float)
    stratify = df["business_category"] if df["business_category"].nunique() > 1 and len(df) >= 100 else None
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.22, random_state=42, stratify=stratify)
    results = []
    fitted = {}
    for name, model in model_suite().items():
        pipe = build_pipeline(model)
        pipe.fit(X_train, y_train)
        pred = np.clip(pipe.predict(X_test), 0, 100)
        metrics = {
            "mae": round(float(mean_absolute_error(y_test, pred)), 4),
            "rmse": round(float(mean_squared_error(y_test, pred) ** 0.5), 4),
            "r2": round(float(r2_score(y_test, pred)), 4),
        }
        results.append({"algorithm": name, "metrics": metrics})
        fitted[name] = pipe
        print(name, metrics)
    best = sorted(results, key=lambda r: (r["metrics"]["mae"], -r["metrics"]["r2"]))[0]
    best_name = best["algorithm"]
    model = fitted[best_name]
    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"{best_name}_opportunity_model.joblib"
    joblib.dump({"pipeline": model, "numeric_features": NUMERIC_FEATURES, "categorical_features": CATEGORICAL_FEATURES, "target": TARGET, "results": results}, artifact_path)
    with eng.begin() as conn:
        if args.activate:
            conn.execute(text("UPDATE ml.model_versions SET is_active = FALSE WHERE business_category IS NULL AND target_name = :target"), {"target": TARGET})
        version_id = conn.execute(text("""
            INSERT INTO ml.model_versions (model_name, business_category, target_name, algorithm, artifact_path, metrics, feature_columns, is_active)
            VALUES ('phase27_opportunity_engine', NULL, :target, :algorithm, :artifact_path, CAST(:metrics AS jsonb), :features, :active)
            RETURNING id
        """), {
            "target": TARGET,
            "algorithm": best_name,
            "artifact_path": str(artifact_path),
            "metrics": json.dumps({"best": best, "all": results}),
            "features": NUMERIC_FEATURES + CATEGORICAL_FEATURES,
            "active": bool(args.activate),
        }).scalar_one()
    all_pred = np.clip(model.predict(X), 0, 100)
    df["predicted_score"] = all_pred
    rows = []
    for _, row in df.iterrows():
        opp_type, zone_key, risk = opportunity_type(float(row.predicted_score), float(row.competition_pressure or 0))
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
            "explanation": json.dumps(explanation(row, float(row.predicted_score))),
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
    print(f"Activated model version {version_id} using {best_name}" if args.activate else f"Trained model version {version_id} using {best_name}")
    print(f"Wrote {len(rows):,} predictions")


if __name__ == "__main__":
    main()
