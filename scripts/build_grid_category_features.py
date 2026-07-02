"""Generate Phase 7 grid-cell + business-category features.

This script creates ml.grid_category_features using the curated spatial layers
available in PostGIS. It is designed to run after dataset imports:
- geo.population_density_grid
- curated.sector_population_features
- curated.establishment_area_features
- curated.osm_poi_features
- curated.lfs_district_features
- curated.movement_features
- geo.analysis_grid or ml.analysis_grid from earlier phases

The script is intentionally defensive: missing optional tables become neutral
features rather than crashing the whole build.
"""
from __future__ import annotations

import argparse
import os
from typing import Iterable

from sqlalchemy import create_engine, inspect, text

DEFAULT_CATEGORIES = ["salon", "pharmacy", "cafe", "grocery", "retail"]


def get_engine():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is required.")
    return create_engine(database_url)


def has_table(engine, schema: str, table: str) -> bool:
    return inspect(engine).has_table(table, schema=schema)


def ensure_analysis_grid(engine, spacing_m: int = 250) -> str:
    """Return the best available grid table, creating a lightweight fallback if needed."""
    if has_table(engine, "geo", "analysis_grid"):
        return "geo.analysis_grid"
    if has_table(engine, "ml", "analysis_grid"):
        return "ml.analysis_grid"

    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS geo"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS geo.analysis_grid (
                grid_id TEXT PRIMARY KEY,
                centroid geometry(Point, 4326) NOT NULL,
                generated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        # Kigali-ish fallback bounding box. Replace with official boundaries when available.
        conn.execute(text("""
            INSERT INTO geo.analysis_grid(grid_id, centroid)
            SELECT
                'fallback_' || row_number() OVER () AS grid_id,
                ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geometry(Point, 4326)
            FROM generate_series(29.85, 30.25, 0.01) lon,
                 generate_series(-2.10, -1.80, 0.01) lat
            ON CONFLICT DO NOTHING
        """))
    return "geo.analysis_grid"


def build_features_sql(grid_table: str, categories: list[str], limit: int | None = None) -> str:
    category_values = ", ".join(f"('{c}')" for c in categories)
    limit_clause = "" if limit is None else f"LIMIT {int(limit)}"

    return f"""
    TRUNCATE ml.grid_category_features;

    WITH categories(category_key) AS (VALUES {category_values}),
    grid AS (
        SELECT
            COALESCE(grid_id::text, id::text, row_number() OVER ()::text) AS grid_id,
            COALESCE(centroid, geom, ST_Centroid(geom))::geometry(Point,4326) AS centroid
        FROM {grid_table}
        WHERE COALESCE(centroid, geom, ST_Centroid(geom)) IS NOT NULL
        {limit_clause}
    ),
    base AS (
        SELECT
            g.grid_id,
            c.category_key AS business_category,
            g.centroid,
            ST_X(g.centroid) AS lon,
            ST_Y(g.centroid) AS lat
        FROM grid g
        CROSS JOIN categories c
    ),
    feature_rows AS (
        SELECT
            b.grid_id,
            b.business_category,
            b.centroid,

            COALESCE(pop500.avg_density, 0) AS population_density_500m,
            COALESCE(pop1000.avg_density, 0) AS population_density_1000m,

            COALESCE((
                SELECT sp.total_population
                FROM curated.sector_population_features sp
                WHERE sp.period = (SELECT MAX(period) FROM curated.sector_population_features)
                ORDER BY sp.total_population DESC NULLS LAST
                LIMIT 1
            ), 0) AS sector_population,

            COALESCE((
                SELECT AVG(employment_rate) FROM curated.lfs_district_features
            ), 0) AS employment_rate,
            COALESCE((
                SELECT AVG(income_proxy) FROM curated.lfs_district_features
            ), 0) AS income_proxy,

            COALESCE(comp300.cnt, 0) AS competitor_count_300m,
            COALESCE(comp500.cnt, 0) AS competitor_count_500m,
            COALESCE(comp1000.cnt, 0) AS competitor_count_1000m,

            COALESCE(commercial500.cnt, 0) AS commercial_poi_count_500m,
            COALESCE(demand_generators.cnt, 0) AS demand_generator_count_1000m,
            COALESCE(complementary.cnt, 0) AS complementary_poi_count_500m,
            COALESCE(markets.nearest_m, 1200) AS market_distance_m,
            COALESCE(schools.cnt, 0) AS school_count_1000m,
            COALESCE(health.cnt, 0) AS health_facility_count_1000m,
            COALESCE(transport.cnt, 0) AS bus_stop_count_500m,
            COALESCE(transport.nearest_m, 1200) AS nearest_bus_stop_m,

            COALESCE(eaf.establishment_count, 0) AS establishment_category_count_area,
            COALESCE(eaf.establishment_count, 0) AS establishment_density_area
        FROM base b
        LEFT JOIN LATERAL ml.get_population_density_near(b.lon, b.lat, 500) pop500 ON TRUE
        LEFT JOIN LATERAL ml.get_population_density_near(b.lon, b.lat, 1000) pop1000 ON TRUE
        LEFT JOIN LATERAL (
            SELECT COUNT(*)::DOUBLE PRECISION AS cnt
            FROM curated.osm_poi_features p
            WHERE p.category_key = b.business_category
              AND ST_DWithin(p.geom::geography, b.centroid::geography, 300)
        ) comp300 ON TRUE
        LEFT JOIN LATERAL (
            SELECT COUNT(*)::DOUBLE PRECISION AS cnt
            FROM curated.osm_poi_features p
            WHERE p.category_key = b.business_category
              AND ST_DWithin(p.geom::geography, b.centroid::geography, 500)
        ) comp500 ON TRUE
        LEFT JOIN LATERAL (
            SELECT COUNT(*)::DOUBLE PRECISION AS cnt
            FROM curated.osm_poi_features p
            WHERE p.category_key = b.business_category
              AND ST_DWithin(p.geom::geography, b.centroid::geography, 1000)
        ) comp1000 ON TRUE
        LEFT JOIN LATERAL (
            SELECT COUNT(*)::DOUBLE PRECISION AS cnt
            FROM curated.osm_poi_features p
            WHERE p.category_key IN ('market','school','health','transport','finance','hotel','cafe','retail')
              AND ST_DWithin(p.geom::geography, b.centroid::geography, 500)
        ) commercial500 ON TRUE
        LEFT JOIN LATERAL (
            SELECT COUNT(*)::DOUBLE PRECISION AS cnt
            FROM curated.osm_poi_features p
            WHERE p.category_key IN ('market','school','health','transport','finance','hotel')
              AND ST_DWithin(p.geom::geography, b.centroid::geography, 1000)
        ) demand_generators ON TRUE
        LEFT JOIN LATERAL (
            SELECT COUNT(*)::DOUBLE PRECISION AS cnt
            FROM curated.osm_poi_features p
            WHERE p.category_key IN ('finance','cafe','retail','market')
              AND p.category_key <> b.business_category
              AND ST_DWithin(p.geom::geography, b.centroid::geography, 500)
        ) complementary ON TRUE
        LEFT JOIN LATERAL (
            SELECT MIN(ST_Distance(p.geom::geography, b.centroid::geography))::DOUBLE PRECISION AS nearest_m
            FROM curated.osm_poi_features p
            WHERE p.category_key = 'market'
        ) markets ON TRUE
        LEFT JOIN LATERAL (
            SELECT COUNT(*)::DOUBLE PRECISION AS cnt
            FROM curated.osm_poi_features p
            WHERE p.category_key = 'school'
              AND ST_DWithin(p.geom::geography, b.centroid::geography, 1000)
        ) schools ON TRUE
        LEFT JOIN LATERAL (
            SELECT COUNT(*)::DOUBLE PRECISION AS cnt
            FROM curated.osm_poi_features p
            WHERE p.category_key = 'health'
              AND ST_DWithin(p.geom::geography, b.centroid::geography, 1000)
        ) health ON TRUE
        LEFT JOIN LATERAL (
            SELECT
                COUNT(*)::DOUBLE PRECISION AS cnt,
                MIN(ST_Distance(p.geom::geography, b.centroid::geography))::DOUBLE PRECISION AS nearest_m
            FROM curated.osm_poi_features p
            WHERE p.category_key = 'transport'
              AND ST_DWithin(p.geom::geography, b.centroid::geography, 1500)
        ) transport ON TRUE
        LEFT JOIN LATERAL (
            SELECT SUM(establishment_count)::DOUBLE PRECISION AS establishment_count
            FROM curated.establishment_area_features f
            WHERE f.business_category = b.business_category
        ) eaf ON TRUE
    )
    INSERT INTO ml.grid_category_features (
        grid_id, business_category, centroid,
        population_density_500m, population_density_1000m, sector_population,
        employment_rate, income_proxy,
        competitor_count_300m, competitor_count_500m, competitor_count_1000m,
        commercial_poi_count_500m, demand_generator_count_1000m, complementary_poi_count_500m,
        market_distance_m, school_count_1000m, health_facility_count_1000m,
        bus_stop_count_500m, nearest_bus_stop_m,
        establishment_category_count_area, establishment_density_area,
        demand_score, accessibility_score, commercial_activity_score, competition_pressure,
        welfare_score, opportunity_gap_score, confidence_score,
        presence_target, business_count_target, ranking_relevance
    )
    SELECT
        grid_id, business_category, centroid,
        population_density_500m, population_density_1000m, sector_population,
        employment_rate, income_proxy,
        competitor_count_300m, competitor_count_500m, competitor_count_1000m,
        commercial_poi_count_500m, demand_generator_count_1000m, complementary_poi_count_500m,
        market_distance_m, school_count_1000m, health_facility_count_1000m,
        bus_stop_count_500m, nearest_bus_stop_m,
        establishment_category_count_area, establishment_density_area,

        LEAST(100, population_density_500m / NULLIF((SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY population_density_500m) FROM feature_rows),0) * 100) AS demand_score,
        LEAST(100, curated.score_from_count(bus_stop_count_500m, 15) * 0.55 + curated.distance_score(nearest_bus_stop_m, 150, 1200) * 0.45) AS accessibility_score,
        LEAST(100, curated.score_from_count(commercial_poi_count_500m, 5) * 0.50 + curated.score_from_count(demand_generator_count_1000m, 2) * 0.30 + curated.distance_score(market_distance_m, 200, 1600) * 0.20) AS commercial_activity_score,
        LEAST(100, competitor_count_500m * 10 + competitor_count_1000m * 3 + establishment_category_count_area * 0.05) AS competition_pressure,
        LEAST(100, COALESCE(employment_rate,0) * 0.60 + COALESCE(income_proxy,0) * 0.40) AS welfare_score,
        -- Initial target: objective supply-demand gap proxy. ML learns and refines this target.
        LEAST(100, GREATEST(0,
            0.36 * LEAST(100, population_density_500m / NULLIF((SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY population_density_500m) FROM feature_rows),0) * 100)
            + 0.22 * LEAST(100, curated.score_from_count(bus_stop_count_500m, 15) * 0.55 + curated.distance_score(nearest_bus_stop_m, 150, 1200) * 0.45)
            + 0.22 * LEAST(100, curated.score_from_count(commercial_poi_count_500m, 5) * 0.50 + curated.score_from_count(demand_generator_count_1000m, 2) * 0.30 + curated.distance_score(market_distance_m, 200, 1600) * 0.20)
            + 0.10 * LEAST(100, COALESCE(employment_rate,0) * 0.60 + COALESCE(income_proxy,0) * 0.40)
            + 0.10 * GREATEST(0, 100 - LEAST(100, competitor_count_500m * 10 + competitor_count_1000m * 3 + establishment_category_count_area * 0.05))
        )) AS opportunity_gap_score,
        LEAST(100, 35 + CASE WHEN population_density_500m > 0 THEN 20 ELSE 0 END + CASE WHEN commercial_poi_count_500m > 0 THEN 20 ELSE 0 END + CASE WHEN competitor_count_1000m > 0 THEN 15 ELSE 0 END + CASE WHEN establishment_category_count_area > 0 THEN 10 ELSE 0 END) AS confidence_score,
        CASE WHEN competitor_count_500m > 0 OR establishment_category_count_area > 0 THEN 1 ELSE 0 END AS presence_target,
        GREATEST(competitor_count_500m, establishment_category_count_area) AS business_count_target,
        CASE
            WHEN population_density_500m > 0
                 AND commercial_poi_count_500m >= 8
                 AND competitor_count_500m <= 3 THEN 3
            WHEN population_density_500m > 0
                 AND commercial_poi_count_500m >= 4
                 AND competitor_count_500m <= 6 THEN 2
            WHEN population_density_500m > 0
                 OR commercial_poi_count_500m >= 2 THEN 1
            ELSE 0
        END AS ranking_relevance
    FROM feature_rows;
    """


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--categories", default=",".join(DEFAULT_CATEGORIES), help="Comma-separated business categories.")
    parser.add_argument("--limit", type=int, default=None, help="Optional grid row limit for testing.")
    args = parser.parse_args()

    categories = [c.strip() for c in args.categories.split(",") if c.strip()]
    engine = get_engine()
    grid_table = ensure_analysis_grid(engine)
    sql = build_features_sql(grid_table, categories, args.limit)
    with engine.begin() as conn:
        conn.execute(text(sql))
        total = conn.execute(text("SELECT COUNT(*) FROM ml.grid_category_features")).scalar()
    print(f"Generated {total:,} grid-category feature rows using grid table {grid_table}.")


if __name__ == "__main__":
    main()
