"""Build live opportunity cache from imported layers.

This script creates a simple Kigali analysis grid when none exists, then populates
ml.live_opportunity_cache. If a trained ML model is available later, replace the
scoring block with model inference while keeping the same output table.
"""
from __future__ import annotations

import argparse
import os
from math import exp

from sqlalchemy import create_engine, text

CATEGORIES = ["salon", "barbershop", "beauty_salon", "pharmacy", "cafe", "restaurant", "grocery", "retail", "mobile_money"]


def clamp(v: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, v))


def sigmoid(v: float) -> float:
    return 1 / (1 + exp(-v))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/bizintel"))
    parser.add_argument("--category", action="append", default=[])
    parser.add_argument("--limit", type=int, default=2500)
    args = parser.parse_args()
    categories = args.category or CATEGORIES
    engine = create_engine(args.database_url)
    with engine.begin() as conn:
        # Use existing geo.analysis_grid when present; otherwise generate a lightweight grid from population points.
        grid_rows = conn.execute(
            text(
                """
                WITH source AS (
                    SELECT id::TEXT AS grid_id, geom
                    FROM geo.population_density_grid
                    ORDER BY id
                    LIMIT :limit
                )
                SELECT grid_id, ST_X(geom) AS lon, ST_Y(geom) AS lat
                FROM source
                """
            ),
            {"limit": args.limit},
        ).mappings().all()
        if not grid_rows:
            raise SystemExit("No population grid points found. Run import_live_datasets.py first.")
        
        for cat in categories:
            conn.execute(text("DELETE FROM ml.live_opportunity_cache WHERE business_category = :category"), {"category": cat})
        payload = []
        for category in categories:
            for row in grid_rows:
                lon = float(row["lon"])
                lat = float(row["lat"])
                pdens = conn.execute(
                    text("SELECT avg_density, max_density, sample_count FROM ml.get_population_density_near(:lon, :lat, 1000)"),
                    {"lon": lon, "lat": lat},
                ).mappings().first() or {}
                avg_density = float(pdens.get("avg_density") or 0)
                sample_count = int(pdens.get("sample_count") or 0)
                demand = clamp(sigmoid((avg_density - 2500) / 2500) * 100)
                # Placeholder until OSM/establishment/road data are fully connected.
                access = clamp(45 + (sample_count / 10) * 8)
                commercial = clamp(35 + demand * 0.35)
                competition = clamp(30 + (commercial * 0.35))
                category_adjustment = {
                    "pharmacy": 3,
                    "grocery": 5,
                    "mobile_money": 4,
                    "cafe": -2,
                    "restaurant": -1,
                    "salon": 2,
                }.get(category, 0)
                # Opportunity rewards demand/access/commercial activity and penalizes excessive competition.
                opportunity = clamp((0.36 * demand) + (0.24 * access) + (0.24 * commercial) + (0.16 * (100 - competition)) + category_adjustment)
                if opportunity >= 75:
                    otype = "high opportunity"
                elif demand >= 70 and competition >= 65:
                    otype = "high demand, high competition"
                elif demand >= 65 and competition < 45:
                    otype = "underserved demand pocket"
                elif opportunity < 40:
                    otype = "weak demand or low access"
                else:
                    otype = "moderate opportunity"
                payload.append({
                    "grid_id": f"pd_{row['grid_id']}",
                    "business_category": category,
                    "opportunity_score": opportunity,
                    "demand_score": demand,
                    "competition_score": competition,
                    "access_score": access,
                    "commercial_activity_score": commercial,
                    "confidence_score": 0.55 if sample_count else 0.25,
                    "opportunity_type": otype,
                    "dominant_factor": "population density" if demand >= access else "access/data coverage",
                    "explanation": '{"method":"phase6_engineered_cache","note":"Replace this scoring with active ML inference after trained model registration."}',
                    "lon": lon,
                    "lat": lat,
                })
        conn.execute(
            text(
                """
                INSERT INTO ml.live_opportunity_cache(
                    grid_id, business_category, opportunity_score, demand_score, competition_score,
                    access_score, commercial_activity_score, confidence_score, opportunity_type,
                    dominant_factor, explanation, geom
                ) VALUES (
                    :grid_id, :business_category, :opportunity_score, :demand_score, :competition_score,
                    :access_score, :commercial_activity_score, :confidence_score, :opportunity_type,
                    :dominant_factor, CAST(:explanation AS jsonb), ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
                )
                ON CONFLICT (grid_id, business_category) DO UPDATE SET
                    opportunity_score = EXCLUDED.opportunity_score,
                    demand_score = EXCLUDED.demand_score,
                    competition_score = EXCLUDED.competition_score,
                    access_score = EXCLUDED.access_score,
                    commercial_activity_score = EXCLUDED.commercial_activity_score,
                    confidence_score = EXCLUDED.confidence_score,
                    opportunity_type = EXCLUDED.opportunity_type,
                    dominant_factor = EXCLUDED.dominant_factor,
                    explanation = EXCLUDED.explanation,
                    generated_at = now()
                """
            ),
            payload,
        )
    print(f"Generated {len(payload)} live opportunity cache rows.")


if __name__ == "__main__":
    main()
