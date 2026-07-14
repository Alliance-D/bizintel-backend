"""Build one row per grid cell and business category for ML training.

Prerequisites:
    python scripts/bootstrap_data_layer.py
    python scripts/generate_analysis_grid.py --radius-m 500
    python scripts/import_osm_business_features.py --truncate
    python scripts/import_population_density.py data/raw/rwa_pd_2020_1km_ASCII_XYZ.csv --truncate
    python scripts/import_population_count.py data/raw/population_count_6456351076777895603.csv --truncate
    python scripts/import_establishment_census.py "<path to establishment census .dta>" --truncate
    python scripts/import_population_welfare.py "<path to PHC5 .dta>" --truncate
    python scripts/import_district_socioeconomic.py --lfs "<LFS .dta>" --vup "<VUP welfare .dta>" --truncate
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
    ), grid_welfare AS (
      -- Resolved once per grid cell (not per cell x category): prefer a
      -- sector-level PHC5 match, fall back to the district-level LFS/VUP row.
      SELECT g.grid_id,
        COALESCE(sector_w.employment_rate, district_w.employment_rate, 0.0) AS employment_rate,
        COALESCE(sector_w.income_proxy, district_w.income_proxy, 0.0) AS income_proxy,
        COALESCE(100 - sector_w.poverty_proxy, 100 - district_w.poverty_proxy, 0.0) AS welfare_proxy
      FROM geo.analysis_grid g
      -- Sector names are not unique nationally (30 sector names repeat across
      -- different districts), so the sector-level join must also match district
      -- or it fans out into duplicate rows per grid cell.
      LEFT JOIN curated.population_welfare_features sector_w
        ON sector_w.area_level = 'sector' AND lower(sector_w.sector) = lower(g.sector) AND lower(sector_w.district) = lower(g.district)
      LEFT JOIN curated.population_welfare_features district_w
        ON district_w.area_level = 'district' AND lower(district_w.district) = lower(g.district)
    ), grid_infra AS (
      -- Road and per-anchor features depend only on the grid cell, not the
      -- category, so they are computed once per cell here (not 5x in feature_rows).
      SELECT g.grid_id,
        COALESCE((SELECT MIN(ST_Distance(o.geom::geography, g.centroid::geography)) FROM curated.osm_poi_features o WHERE o.category_key = 'transport' AND o.tags->>'amenity' = 'bus_station'), 5000) AS nearest_bus_station_m,
        COALESCE((SELECT MIN(ST_Distance(o.geom::geography, g.centroid::geography)) FROM curated.osm_poi_features o WHERE o.category_key = 'school'), 5000) AS nearest_school_m,
        COALESCE((SELECT MIN(ST_Distance(o.geom::geography, g.centroid::geography)) FROM curated.osm_poi_features o WHERE o.category_key = 'health'), 5000) AS nearest_health_m,
        COALESCE((SELECT MIN(ST_Distance(o.geom::geography, g.centroid::geography)) FROM curated.osm_poi_features o WHERE o.category_key = 'finance'), 5000) AS nearest_finance_m,
        COALESCE((SELECT ST_Distance(r.geom::geography, g.centroid::geography) FROM curated.osm_road_features r WHERE r.is_main ORDER BY r.geom <-> g.centroid LIMIT 1), 5000) AS distance_to_main_road_m,
        COALESCE((SELECT SUM(ST_Length(ST_Intersection(r.geom, ST_Buffer(g.centroid::geography, 500)::geometry)::geography)) FROM curated.osm_road_features r WHERE r.is_street AND ST_DWithin(r.geom::geography, g.centroid::geography, 500)), 0) AS road_density_500m,
        COALESCE((SELECT COUNT(*) FROM curated.osm_road_intersections i WHERE ST_DWithin(i.geom::geography, g.centroid::geography, 500)), 0) AS intersection_density_500m,
        COALESCE((SELECT CASE
            WHEN r.highway IN ('motorway','trunk','primary','secondary','tertiary','motorway_link','trunk_link','primary_link','secondary_link','tertiary_link') THEN 'main'
            WHEN r.highway IN ('residential','living_street','unclassified','road') THEN 'residential'
            WHEN r.highway = 'service' THEN 'service'
            WHEN r.highway IN ('path','footway','steps','track','cycleway','bridleway','pedestrian') THEN 'path'
            ELSE 'other' END
          FROM curated.osm_road_features r ORDER BY r.geom <-> g.centroid LIMIT 1), 'other') AS road_class_nearest
      FROM geo.analysis_grid g
    ), feature_rows AS (
      SELECT
        b.*,
        gw.employment_rate, gw.income_proxy, gw.welfare_proxy,
        COALESCE((SELECT AVG(p.population_density) FROM curated.population_density_points p WHERE ST_DWithin(p.geom::geography, b.centroid::geography, 500)), 0) AS population_density_500m,
        COALESCE((SELECT AVG(p.population_density) FROM curated.population_density_points p WHERE ST_DWithin(p.geom::geography, b.centroid::geography, 1000)), 0) AS population_density_1000m,
        COALESCE((SELECT pc.total_population FROM curated.population_count_features pc WHERE lower(pc.district) = lower(COALESCE(b.district, pc.district)) AND (b.sector IS NULL OR lower(pc.sector) = lower(b.sector)) ORDER BY pc.period DESC LIMIT 1), 0) AS sector_population,
        COALESCE((SELECT COUNT(*) FROM curated.osm_poi_features o WHERE o.category_key = b.business_category AND ST_DWithin(o.geom::geography, b.centroid::geography, 300)), 0) AS competitor_count_300m,
        COALESCE((SELECT COUNT(*) FROM curated.osm_poi_features o WHERE o.category_key = b.business_category AND ST_DWithin(o.geom::geography, b.centroid::geography, 500)), 0) AS competitor_count_500m,
        COALESCE((SELECT COUNT(*) FROM curated.osm_poi_features o WHERE o.category_key = b.business_category AND ST_DWithin(o.geom::geography, b.centroid::geography, 1000)), 0) AS competitor_count_1000m,
        COALESCE((SELECT MIN(ST_Distance(o.geom::geography, b.centroid::geography)) FROM curated.osm_poi_features o WHERE o.category_key = b.business_category), 5000) AS nearest_competitor_m,
        COALESCE((SELECT COUNT(*) FROM curated.osm_poi_features o WHERE o.category_key IN ('pharmacy','restaurant','cafe','grocery','salon','commercial_support','finance') AND o.category_key <> b.business_category AND ST_DWithin(o.geom::geography, b.centroid::geography, 500)), 0) AS complementary_poi_count_500m,
        COALESCE((SELECT COUNT(*) FROM curated.osm_poi_features o WHERE o.category_key IN ('pharmacy','restaurant','cafe','grocery','salon','commercial_support','finance','market') AND o.category_key <> b.business_category AND ST_DWithin(o.geom::geography, b.centroid::geography, 500)), 0) AS commercial_poi_count_500m,
        COALESCE((SELECT COUNT(*) FROM curated.osm_poi_features o WHERE o.category_key IN ('school','health','market','transport') AND ST_DWithin(o.geom::geography, b.centroid::geography, 1000)), 0) AS demand_generator_count_1000m,
        COALESCE((SELECT MIN(ST_Distance(o.geom::geography, b.centroid::geography)) FROM curated.osm_poi_features o WHERE o.category_key = 'market'), 5000) AS market_distance_m,
        COALESCE((SELECT COUNT(*) FROM curated.osm_poi_features o WHERE o.category_key = 'school' AND ST_DWithin(o.geom::geography, b.centroid::geography, 1000)), 0) AS school_count_1000m,
        COALESCE((SELECT COUNT(*) FROM curated.osm_poi_features o WHERE o.category_key = 'health' AND ST_DWithin(o.geom::geography, b.centroid::geography, 1000)), 0) AS health_facility_count_1000m,
        COALESCE((SELECT COUNT(*) FROM curated.osm_poi_features o WHERE o.category_key = 'transport' AND ST_DWithin(o.geom::geography, b.centroid::geography, 500)), 0) AS bus_stop_count_500m,
        COALESCE((SELECT MIN(ST_Distance(o.geom::geography, b.centroid::geography)) FROM curated.osm_poi_features o WHERE o.category_key = 'transport'), 2500) AS nearest_bus_stop_m,
        COALESCE((SELECT SUM(e.establishment_count) FROM curated.establishment_area_features e WHERE e.business_category = b.business_category AND (e.district IS NULL OR b.district IS NULL OR lower(e.district) = lower(b.district)) AND (e.sector IS NULL OR b.sector IS NULL OR lower(e.sector) = lower(b.sector))), 0) AS establishment_category_count_area,
        gi.nearest_bus_station_m, gi.nearest_school_m, gi.nearest_health_m, gi.nearest_finance_m,
        gi.distance_to_main_road_m, gi.road_density_500m, gi.intersection_density_500m, gi.road_class_nearest
      FROM base b
      JOIN grid_welfare gw ON gw.grid_id = b.grid_id
      JOIN grid_infra gi ON gi.grid_id = b.grid_id
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
          s.welfare_proxy * p.welfare_weight
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
      nearest_bus_station_m, nearest_school_m, nearest_health_m, nearest_finance_m,
      distance_to_main_road_m, road_density_500m, intersection_density_500m, road_class_nearest,
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
      nearest_bus_station_m, nearest_school_m, nearest_health_m, nearest_finance_m,
      distance_to_main_road_m, road_density_500m, intersection_density_500m, road_class_nearest,
      establishment_category_count_area, 0,
      demand_raw, access_raw, activity_raw, competition_raw,
      welfare_proxy,
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
      nearest_bus_station_m = EXCLUDED.nearest_bus_station_m,
      nearest_school_m = EXCLUDED.nearest_school_m,
      nearest_health_m = EXCLUDED.nearest_health_m,
      nearest_finance_m = EXCLUDED.nearest_finance_m,
      distance_to_main_road_m = EXCLUDED.distance_to_main_road_m,
      road_density_500m = EXCLUDED.road_density_500m,
      intersection_density_500m = EXCLUDED.intersection_density_500m,
      road_class_nearest = EXCLUDED.road_class_nearest,
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
        # Idempotent: bring an existing table up to date with the road/anchor columns.
        conn.execute(text("""
            ALTER TABLE ml.grid_category_features
              ADD COLUMN IF NOT EXISTS nearest_bus_station_m DOUBLE PRECISION,
              ADD COLUMN IF NOT EXISTS nearest_school_m DOUBLE PRECISION,
              ADD COLUMN IF NOT EXISTS nearest_health_m DOUBLE PRECISION,
              ADD COLUMN IF NOT EXISTS nearest_finance_m DOUBLE PRECISION,
              ADD COLUMN IF NOT EXISTS distance_to_main_road_m DOUBLE PRECISION,
              ADD COLUMN IF NOT EXISTS road_density_500m DOUBLE PRECISION DEFAULT 0,
              ADD COLUMN IF NOT EXISTS intersection_density_500m INTEGER DEFAULT 0,
              ADD COLUMN IF NOT EXISTS road_class_nearest TEXT
        """))
        if args.truncate:
            conn.execute(text("TRUNCATE ml.grid_category_features RESTART IDENTITY"))
        conn.execute(sql)
        count = conn.execute(text("SELECT COUNT(*) FROM ml.grid_category_features")).scalar()
    print(f"Built {count:,} grid-category feature rows")


if __name__ == "__main__":
    main()
