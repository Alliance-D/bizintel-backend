"""Generate grid-cell + business-category feature rows in ml.training_features.

This script assumes:
- geo.analysis_grid exists
- geo.population_density_grid may exist
- geo.osm_pois / geo.osm_roads may exist
- curated area-level tables may exist

It is safe to run even when some optional layers are empty. Missing data produces
low confidence and null/zero feature values rather than failing.
"""
from __future__ import annotations

import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/bizintel")
BUSINESS_CATEGORIES = os.getenv(
    "BUSINESS_CATEGORIES",
    "salon,barbershop,beauty_salon,pharmacy,cafe,restaurant,grocery,retail,mobile_money",
).split(",")


def ensure_category_profiles(conn) -> None:
    rows = [
        {"business_category": "salon", "label": "Hair salon", "confidence_level": "high"},
        {"business_category": "barbershop", "label": "Barbershop", "confidence_level": "high"},
        {"business_category": "beauty_salon", "label": "Beauty salon", "confidence_level": "high"},
        {"business_category": "pharmacy", "label": "Pharmacy", "confidence_level": "medium"},
        {"business_category": "cafe", "label": "Café", "confidence_level": "medium"},
        {"business_category": "restaurant", "label": "Restaurant", "confidence_level": "medium"},
        {"business_category": "grocery", "label": "Grocery shop", "confidence_level": "medium"},
        {"business_category": "retail", "label": "Retail shop", "confidence_level": "medium"},
        {"business_category": "mobile_money", "label": "Mobile money agent", "confidence_level": "medium"},
    ]
    conn.execute(text("""
        INSERT INTO ml.category_profiles (business_category, label, confidence_level)
        VALUES (:business_category, :label, :confidence_level)
        ON CONFLICT (business_category) DO UPDATE SET
            label = EXCLUDED.label,
            confidence_level = EXCLUDED.confidence_level
    """), rows)


def main() -> None:
    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        ensure_category_profiles(conn)
        for category in BUSINESS_CATEGORIES:
            category = category.strip()
            if not category:
                continue
            conn.execute(text("""
                INSERT INTO ml.training_features (
                    grid_id, business_category,
                    demand_score, population_density_500m, population_density_1000m,
                    access_score, nearest_main_road_m, bus_stop_count_500m, market_distance_m,
                    commercial_activity_score, commercial_poi_count_500m,
                    competitor_count_300m, competitor_count_500m, competitor_count_1000m,
                    opportunity_gap_score
                )
                SELECT
                    g.grid_id,
                    :category AS business_category,
                    LEAST(100, COALESCE(f.population_density_500m, 0) / 100.0) AS demand_score,
                    f.population_density_500m,
                    f.population_density_1000m,
                    GREATEST(0, 100 - COALESCE(f.nearest_main_road_m, 9999) / 20.0) AS access_score,
                    f.nearest_main_road_m,
                    f.bus_stop_count_500m,
                    f.market_distance_m,
                    LEAST(100, COALESCE(f.commercial_poi_count_500m, 0) * 5.0) AS commercial_activity_score,
                    f.commercial_poi_count_500m,
                    f.competitor_count_300m,
                    f.competitor_count_500m,
                    f.competitor_count_1000m,
                    LEAST(100, GREATEST(0,
                        (LEAST(100, COALESCE(f.population_density_500m, 0) / 100.0) * 0.45) +
                        (GREATEST(0, 100 - COALESCE(f.nearest_main_road_m, 9999) / 20.0) * 0.25) +
                        (LEAST(100, COALESCE(f.commercial_poi_count_500m, 0) * 5.0) * 0.20) -
                        (COALESCE(f.competitor_count_500m, 0) * 3.0)
                    )) AS opportunity_gap_score
                FROM geo.analysis_grid g
                CROSS JOIN LATERAL ml.extract_location_features_sql(
                    ST_Y(g.centroid), ST_X(g.centroid), :category, 500
                ) AS f
                ON CONFLICT (grid_id, business_category) DO UPDATE SET
                    demand_score = EXCLUDED.demand_score,
                    population_density_500m = EXCLUDED.population_density_500m,
                    population_density_1000m = EXCLUDED.population_density_1000m,
                    access_score = EXCLUDED.access_score,
                    nearest_main_road_m = EXCLUDED.nearest_main_road_m,
                    bus_stop_count_500m = EXCLUDED.bus_stop_count_500m,
                    market_distance_m = EXCLUDED.market_distance_m,
                    commercial_activity_score = EXCLUDED.commercial_activity_score,
                    commercial_poi_count_500m = EXCLUDED.commercial_poi_count_500m,
                    competitor_count_300m = EXCLUDED.competitor_count_300m,
                    competitor_count_500m = EXCLUDED.competitor_count_500m,
                    competitor_count_1000m = EXCLUDED.competitor_count_1000m,
                    opportunity_gap_score = EXCLUDED.opportunity_gap_score,
                    generated_at = now()
            """), {"category": category})
        count = conn.execute(text("SELECT COUNT(*) FROM ml.training_features")).scalar_one()
    print(f"Generated/updated {count:,} training feature rows")


if __name__ == "__main__":
    main()
