"""Build one row per grid cell and business category for ML training.

Prerequisites:
    python scripts/bootstrap_data_layer.py
    python scripts/generate_analysis_grid.py --radius-m 500
    python scripts/import_osm_business_features.py --truncate
    python scripts/import_population_density.py data/raw/rwa_pd_2020_1km_ASCII_XYZ.csv --truncate
    python scripts/import_population_count.py data/raw/population_count_6456351076777895603.csv --truncate
"""
from __future__ import annotations

import argparse
import os
from sqlalchemy import create_engine, text


def engine():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is required")
    return create_engine(url)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--truncate", action="store_true")
    args = parser.parse_args()
    eng = engine()
    sql = text("""
    WITH categories AS (
      SELECT category_key FROM curated.business_category_profiles WHERE is_active = TRUE
    ), base AS (
      SELECT g.grid_id, c.category_key AS business_category, g.geom, g.centroid, g.district, g.sector, g.cell
      FROM geo.analysis_grid g CROSS JOIN categories c
    ), feature_rows AS (
      SELECT
        b.*,
        COALESCE((SELECT AVG(p.population_density) FROM curated.population_density_points p WHERE ST_DWithin(p.geom::geography, b.centroid::geography, 500)), 0) AS population_density_500m,
        COALESCE((SELECT AVG(p.population_density) FROM curated.population_density_points p WHERE ST_DWithin(p.geom::geography, b.centroid::geography, 1000)), 0) AS population_density_1000m,
        COALESCE((SELECT pc.total_population FROM curated.population_count_features pc WHERE lower(pc.district) = lower(COALESCE(b.district, pc.district)) AND (b.sector IS NULL OR lower(pc.sector) = lower(b.sector)) ORDER BY pc.period DESC LIMIT 1), 0) AS sector_population,
        COALESCE((SELECT COUNT(*) FROM curated.osm_poi_features o WHERE o.category_key = b.business_category AND ST_DWithin(o.geom::geography, b.centroid::geography, 300)), 0) AS competitor_count_300m,
        COALESCE((SELECT COUNT(*) FROM curated.osm_poi_features o WHERE o.category_key = b.business_category AND ST_DWithin(o.geom::geography, b.centroid::geography, 500)), 0) AS competitor_count_500m,
        COALESCE((SELECT COUNT(*) FROM curated.osm_poi_features o WHERE o.category_key = b.business_category AND ST_DWithin(o.geom::geography, b.centroid::geography, 1000)), 0) AS competitor_count_1000m,
        COALESCE((SELECT MIN(ST_Distance(o.geom::geography, b.centroid::geography)) FROM curated.osm_poi_features o WHERE o.category_key = b.business_category), 5000) AS nearest_competitor_m,
        COALESCE((SELECT COUNT(*) FROM curated.osm_poi_features o WHERE o.category_key IN ('pharmacy','restaurant','cafe','grocery','salon','commercial_support','finance') AND o.category_key <> b.business_category AND ST_DWithin(o.geom::geography, b.centroid::geography, 500)), 0) AS complementary_poi_count_500m,
        COALESCE((SELECT COUNT(*) FROM curated.osm_poi_features o WHERE o.category_key IN ('pharmacy','restaurant','cafe','grocery','salon','commercial_support','finance','market') AND ST_DWithin(o.geom::geography, b.centroid::geography, 500)), 0) AS commercial_poi_count_500m,
        COALESCE((SELECT COUNT(*) FROM curated.osm_poi_features o WHERE o.category_key IN ('school','health','market','transport') AND ST_DWithin(o.geom::geography, b.centroid::geography, 1000)), 0) AS demand_generator_count_1000m,
        COALESCE((SELECT MIN(ST_Distance(o.geom::geography, b.centroid::geography)) FROM curated.osm_poi_features o WHERE o.category_key = 'market'), 5000) AS market_distance_m,
        COALESCE((SELECT COUNT(*) FROM curated.osm_poi_features o WHERE o.category_key = 'school' AND ST_DWithin(o.geom::geography, b.centroid::geography, 1000)), 0) AS school_count_1000m,
        COALESCE((SELECT COUNT(*) FROM curated.osm_poi_features o WHERE o.category_key = 'health' AND ST_DWithin(o.geom::geography, b.centroid::geography, 1000)), 0) AS health_facility_count_1000m,
        COALESCE((SELECT COUNT(*) FROM curated.osm_poi_features o WHERE o.category_key = 'transport' AND ST_DWithin(o.geom::geography, b.centroid::geography, 500)), 0) AS bus_stop_count_500m,
        COALESCE((SELECT MIN(ST_Distance(o.geom::geography, b.centroid::geography)) FROM curated.osm_poi_features o WHERE o.category_key = 'transport'), 2500) AS nearest_bus_stop_m,
        COALESCE((SELECT SUM(e.establishment_count) FROM curated.establishment_area_features e WHERE e.business_category = b.business_category AND (e.district IS NULL OR b.district IS NULL OR lower(e.district) = lower(b.district)) AND (e.sector IS NULL OR b.sector IS NULL OR lower(e.sector) = lower(b.sector))), 0) AS establishment_category_count_area,
        0.0 AS employment_rate,
        0.0 AS income_proxy,
        0.0 AS welfare_proxy
      FROM base b
    ), scored AS (
      SELECT fr.*,
        curated.score_from_count(population_density_500m, NULLIF((SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY population_density_500m) FROM feature_rows), 0)) AS demand_raw,
        (curated.score_from_count(bus_stop_count_500m, 12) * 0.50 + curated.distance_score(nearest_bus_stop_m, 150, 1800) * 0.50) AS access_raw,
        (curated.score_from_count(commercial_poi_count_500m, 12) * 0.45 + curated.score_from_count(demand_generator_count_1000m, 8) * 0.30 + curated.distance_score(market_distance_m, 200, 2000) * 0.25) AS activity_raw,
        LEAST(100, competitor_count_500m * 12 + competitor_count_1000m * 3 + establishment_category_count_area * 0.05) AS competition_raw,
        LEAST(100, 35 + CASE WHEN population_density_500m > 0 THEN 20 ELSE 0 END + CASE WHEN commercial_poi_count_500m > 0 THEN 15 ELSE 0 END + CASE WHEN competitor_count_1000m > 0 THEN 15 ELSE 0 END + CASE WHEN sector_population > 0 THEN 15 ELSE 0 END) AS confidence_raw
      FROM feature_rows fr
    ), weighted AS (
      SELECT s.*, p.demand_weight, p.access_weight, p.commercial_weight, p.competition_weight, p.welfare_weight,
        LEAST(100, GREATEST(0,
          s.demand_raw * p.demand_weight +
          s.access_raw * p.access_weight +
          s.activity_raw * p.commercial_weight +
          GREATEST(0, 100 - s.competition_raw) * p.competition_weight +
          ((s.demand_raw * 0.6) + (s.activity_raw * 0.25) + (GREATEST(0, 100 - s.competition_raw) * 0.15)) * p.welfare_weight
        )) AS opportunity_gap_score_calc
      FROM scored s
      JOIN curated.business_category_profiles p ON p.category_key = s.business_category
    )
    INSERT INTO ml.grid_category_features (
      grid_id, business_category, geom, centroid, district, sector, cell,
      population_density_500m, population_density_1000m, sector_population,
      employment_rate, income_proxy, welfare_proxy,
      competitor_count_300m, competitor_count_500m, competitor_count_1000m, nearest_competitor_m,
      complementary_poi_count_500m, commercial_poi_count_500m, demand_generator_count_1000m,
      market_distance_m, school_count_1000m, health_facility_count_1000m, bus_stop_count_500m, nearest_bus_stop_m,
      establishment_category_count_area, establishment_density_area,
      demand_score, accessibility_score, commercial_activity_score, competition_pressure,
      welfare_score, opportunity_gap_score, confidence_score,
      presence_target, business_count_target, ranking_relevance, feature_payload
    )
    SELECT
      grid_id, business_category, geom, centroid, district, sector, cell,
      population_density_500m, population_density_1000m, sector_population,
      employment_rate, income_proxy, welfare_proxy,
      competitor_count_300m, competitor_count_500m, competitor_count_1000m, nearest_competitor_m,
      complementary_poi_count_500m, commercial_poi_count_500m, demand_generator_count_1000m,
      market_distance_m, school_count_1000m, health_facility_count_1000m, bus_stop_count_500m, nearest_bus_stop_m,
      establishment_category_count_area, 0,
      demand_raw, access_raw, activity_raw, competition_raw,
      (demand_raw * 0.6 + activity_raw * 0.25 + GREATEST(0, 100 - competition_raw) * 0.15),
      opportunity_gap_score_calc, confidence_raw,
      CASE WHEN competitor_count_1000m > 0 OR establishment_category_count_area > 0 THEN 1 ELSE 0 END,
      competitor_count_1000m + establishment_category_count_area,
      opportunity_gap_score_calc,
      jsonb_build_object(
        'nearest_competitor_m', nearest_competitor_m,
        'population_density_500m', population_density_500m,
        'bus_stop_count_500m', bus_stop_count_500m,
        'commercial_poi_count_500m', commercial_poi_count_500m,
        'demand_generator_count_1000m', demand_generator_count_1000m
      )
    FROM weighted
    ON CONFLICT (grid_id, business_category) DO UPDATE SET
      geom = EXCLUDED.geom,
      centroid = EXCLUDED.centroid,
      district = EXCLUDED.district,
      sector = EXCLUDED.sector,
      cell = EXCLUDED.cell,
      population_density_500m = EXCLUDED.population_density_500m,
      population_density_1000m = EXCLUDED.population_density_1000m,
      sector_population = EXCLUDED.sector_population,
      competitor_count_300m = EXCLUDED.competitor_count_300m,
      competitor_count_500m = EXCLUDED.competitor_count_500m,
      competitor_count_1000m = EXCLUDED.competitor_count_1000m,
      nearest_competitor_m = EXCLUDED.nearest_competitor_m,
      complementary_poi_count_500m = EXCLUDED.complementary_poi_count_500m,
      commercial_poi_count_500m = EXCLUDED.commercial_poi_count_500m,
      demand_generator_count_1000m = EXCLUDED.demand_generator_count_1000m,
      bus_stop_count_500m = EXCLUDED.bus_stop_count_500m,
      nearest_bus_stop_m = EXCLUDED.nearest_bus_stop_m,
      demand_score = EXCLUDED.demand_score,
      accessibility_score = EXCLUDED.accessibility_score,
      commercial_activity_score = EXCLUDED.commercial_activity_score,
      competition_pressure = EXCLUDED.competition_pressure,
      welfare_score = EXCLUDED.welfare_score,
      opportunity_gap_score = EXCLUDED.opportunity_gap_score,
      confidence_score = EXCLUDED.confidence_score,
      presence_target = EXCLUDED.presence_target,
      business_count_target = EXCLUDED.business_count_target,
      ranking_relevance = EXCLUDED.ranking_relevance,
      feature_payload = EXCLUDED.feature_payload,
      updated_at = now();
    """)
    with eng.begin() as conn:
        if args.truncate:
            conn.execute(text("TRUNCATE ml.grid_category_features RESTART IDENTITY"))
        conn.execute(sql)
        count = conn.execute(text("SELECT COUNT(*) FROM ml.grid_category_features")).scalar()
    print(f"Built {count:,} grid-category feature rows")


if __name__ == "__main__":
    main()
