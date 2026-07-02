-- Phase 7: Real ML-backed opportunity engine + OSM/Establishment feature layer
-- Apply after 010_live_dataset_integration.sql.

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS geo;
CREATE SCHEMA IF NOT EXISTS curated;
CREATE SCHEMA IF NOT EXISTS ml;

-- Business category definitions used by ML, scoring, UI, and data ingestion.
CREATE TABLE IF NOT EXISTS curated.business_category_profiles (
    id BIGSERIAL PRIMARY KEY,
    category_key TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    description TEXT,
    demand_weight DOUBLE PRECISION NOT NULL DEFAULT 0.30,
    access_weight DOUBLE PRECISION NOT NULL DEFAULT 0.25,
    commercial_weight DOUBLE PRECISION NOT NULL DEFAULT 0.20,
    competition_weight DOUBLE PRECISION NOT NULL DEFAULT 0.20,
    welfare_weight DOUBLE PRECISION NOT NULL DEFAULT 0.05,
    competitor_osm_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    demand_generator_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    complementary_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    min_confidence_threshold DOUBLE PRECISION NOT NULL DEFAULT 0.45,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO curated.business_category_profiles (
    category_key, display_name, description, demand_weight, access_weight,
    commercial_weight, competition_weight, welfare_weight, competitor_osm_tags,
    demand_generator_tags, complementary_tags
) VALUES
('salon', 'Salon / Personal Care', 'Hair salons, barbershops, beauty and nail services.', 0.34, 0.20, 0.20, 0.21, 0.05,
 '[{"key":"shop","value":"hairdresser"},{"key":"shop","value":"beauty"},{"key":"shop","value":"cosmetics"}]',
 '[{"key":"amenity","value":"marketplace"},{"key":"amenity","value":"school"},{"key":"shop","value":"supermarket"}]',
 '[{"key":"amenity","value":"bank"},{"key":"amenity","value":"cafe"},{"key":"amenity","value":"restaurant"}]'),
('pharmacy', 'Pharmacy / Health Retail', 'Pharmacies and health-related retail services.', 0.30, 0.27, 0.14, 0.24, 0.05,
 '[{"key":"amenity","value":"pharmacy"},{"key":"healthcare","value":"pharmacy"}]',
 '[{"key":"amenity","value":"hospital"},{"key":"amenity","value":"clinic"},{"key":"healthcare","value":"clinic"}]',
 '[{"key":"amenity","value":"bank"},{"key":"shop","value":"supermarket"}]'),
('cafe', 'Café / Food Away From Home', 'Cafés, small restaurants and food-away-from-home opportunities.', 0.24, 0.24, 0.28, 0.18, 0.06,
 '[{"key":"amenity","value":"cafe"},{"key":"amenity","value":"restaurant"},{"key":"amenity","value":"fast_food"}]',
 '[{"key":"amenity","value":"school"},{"key":"office","value":"*"},{"key":"amenity","value":"marketplace"}]',
 '[{"key":"amenity","value":"bank"},{"key":"shop","value":"supermarket"},{"key":"tourism","value":"hotel"}]'),
('grocery', 'Grocery / Daily Retail', 'Small grocery, mini-market and daily household retail.', 0.36, 0.20, 0.18, 0.20, 0.06,
 '[{"key":"shop","value":"convenience"},{"key":"shop","value":"supermarket"},{"key":"shop","value":"grocery"}]',
 '[{"key":"landuse","value":"residential"},{"key":"amenity","value":"school"},{"key":"amenity","value":"bus_station"}]',
 '[{"key":"amenity","value":"bank"},{"key":"amenity","value":"marketplace"}]'),
('retail', 'General Retail', 'Small retail shops and consumer goods businesses.', 0.28, 0.23, 0.27, 0.17, 0.05,
 '[{"key":"shop","value":"*"}]',
 '[{"key":"amenity","value":"marketplace"},{"key":"shop","value":"mall"},{"key":"amenity","value":"bank"}]',
 '[{"key":"amenity","value":"restaurant"},{"key":"tourism","value":"hotel"}]')
ON CONFLICT (category_key) DO NOTHING;

-- Normalized OSM-derived point layer for app features. This is intentionally smaller
-- than raw OSM tables and can be rebuilt any time from osm2pgsql/import scripts.
CREATE TABLE IF NOT EXISTS curated.osm_poi_features (
    id BIGSERIAL PRIMARY KEY,
    osm_id TEXT,
    name TEXT,
    category_key TEXT,
    primary_key TEXT,
    primary_value TEXT,
    tags JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_layer TEXT,
    geom geometry(Point, 4326) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_osm_poi_features_geom ON curated.osm_poi_features USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_osm_poi_features_category ON curated.osm_poi_features(category_key);
CREATE INDEX IF NOT EXISTS idx_osm_poi_features_key_value ON curated.osm_poi_features(primary_key, primary_value);

-- Grid category feature table: one row = grid cell + business category.
-- This is the Phase 7 canonical ML training/inference table.
CREATE TABLE IF NOT EXISTS ml.grid_category_features (
    id BIGSERIAL PRIMARY KEY,
    grid_id TEXT NOT NULL,
    business_category TEXT NOT NULL,
    centroid geometry(Point, 4326) NOT NULL,
    district TEXT,
    sector TEXT,
    cell TEXT,

    -- Demand
    population_density_500m DOUBLE PRECISION DEFAULT 0,
    population_density_1000m DOUBLE PRECISION DEFAULT 0,
    sector_population DOUBLE PRECISION DEFAULT 0,
    youth_share DOUBLE PRECISION DEFAULT 0,
    female_share DOUBLE PRECISION DEFAULT 0,
    household_density_proxy DOUBLE PRECISION DEFAULT 0,

    -- Socio-economic / purchasing power
    employment_rate DOUBLE PRECISION DEFAULT 0,
    income_proxy DOUBLE PRECISION DEFAULT 0,
    welfare_proxy DOUBLE PRECISION DEFAULT 0,
    poverty_proxy DOUBLE PRECISION DEFAULT 0,

    -- Access
    nearest_main_road_m DOUBLE PRECISION DEFAULT 0,
    road_access_score DOUBLE PRECISION DEFAULT 0,
    bus_stop_count_500m DOUBLE PRECISION DEFAULT 0,
    nearest_bus_stop_m DOUBLE PRECISION DEFAULT 0,
    mobility_local_share DOUBLE PRECISION DEFAULT 0,

    -- Commercial activity
    commercial_poi_count_500m DOUBLE PRECISION DEFAULT 0,
    demand_generator_count_1000m DOUBLE PRECISION DEFAULT 0,
    complementary_poi_count_500m DOUBLE PRECISION DEFAULT 0,
    market_distance_m DOUBLE PRECISION DEFAULT 0,
    school_count_1000m DOUBLE PRECISION DEFAULT 0,
    health_facility_count_1000m DOUBLE PRECISION DEFAULT 0,
    business_diversity_index DOUBLE PRECISION DEFAULT 0,

    -- Competition / supply
    competitor_count_300m DOUBLE PRECISION DEFAULT 0,
    competitor_count_500m DOUBLE PRECISION DEFAULT 0,
    competitor_count_1000m DOUBLE PRECISION DEFAULT 0,
    establishment_category_count_area DOUBLE PRECISION DEFAULT 0,
    establishment_density_area DOUBLE PRECISION DEFAULT 0,
    supply_pressure_score DOUBLE PRECISION DEFAULT 0,

    -- Composite engineered inputs
    demand_score DOUBLE PRECISION DEFAULT 0,
    accessibility_score DOUBLE PRECISION DEFAULT 0,
    commercial_activity_score DOUBLE PRECISION DEFAULT 0,
    competition_pressure DOUBLE PRECISION DEFAULT 0,
    welfare_score DOUBLE PRECISION DEFAULT 0,
    opportunity_gap_score DOUBLE PRECISION DEFAULT 0,
    confidence_score DOUBLE PRECISION DEFAULT 0,

    -- Targets available for model comparison
    presence_target INTEGER DEFAULT 0,
    business_count_target DOUBLE PRECISION DEFAULT 0,
    ranking_relevance INTEGER DEFAULT 0,

    generated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_grid_category_features ON ml.grid_category_features(grid_id, business_category);
CREATE INDEX IF NOT EXISTS idx_grid_category_features_centroid ON ml.grid_category_features USING GIST(centroid);
CREATE INDEX IF NOT EXISTS idx_grid_category_features_category ON ml.grid_category_features(business_category);
CREATE INDEX IF NOT EXISTS idx_grid_category_features_score ON ml.grid_category_features(business_category, opportunity_gap_score DESC);

-- Cache of ML predictions for map rendering and fast app reads.
CREATE TABLE IF NOT EXISTS ml.ml_opportunity_predictions (
    id BIGSERIAL PRIMARY KEY,
    grid_id TEXT NOT NULL,
    business_category TEXT NOT NULL,
    opportunity_score DOUBLE PRECISION NOT NULL,
    opportunity_rank DOUBLE PRECISION,
    demand_score DOUBLE PRECISION,
    accessibility_score DOUBLE PRECISION,
    commercial_activity_score DOUBLE PRECISION,
    competition_pressure DOUBLE PRECISION,
    confidence_score DOUBLE PRECISION,
    opportunity_type TEXT,
    explanation JSONB DEFAULT '{}'::jsonb,
    model_version_id BIGINT,
    geom geometry(Point, 4326) NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ml_opportunity_predictions ON ml.ml_opportunity_predictions(grid_id, business_category, (COALESCE(model_version_id,0)));
CREATE INDEX IF NOT EXISTS idx_ml_opportunity_predictions_geom ON ml.ml_opportunity_predictions USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_ml_opportunity_predictions_category_score ON ml.ml_opportunity_predictions(business_category, opportunity_score DESC);

CREATE OR REPLACE FUNCTION curated.score_from_count(p_count DOUBLE PRECISION, p_scale DOUBLE PRECISION DEFAULT 10)
RETURNS DOUBLE PRECISION
LANGUAGE SQL
IMMUTABLE
AS $$
    SELECT LEAST(100, GREATEST(0, COALESCE(p_count,0) * p_scale));
$$;

CREATE OR REPLACE FUNCTION curated.distance_score(p_distance_m DOUBLE PRECISION, p_good_m DOUBLE PRECISION DEFAULT 150, p_bad_m DOUBLE PRECISION DEFAULT 1200)
RETURNS DOUBLE PRECISION
LANGUAGE SQL
IMMUTABLE
AS $$
    SELECT CASE
        WHEN p_distance_m IS NULL OR p_distance_m <= 0 THEN 50
        WHEN p_distance_m <= p_good_m THEN 100
        WHEN p_distance_m >= p_bad_m THEN 0
        ELSE 100 - ((p_distance_m - p_good_m) / NULLIF(p_bad_m - p_good_m, 0)) * 100
    END;
$$;

CREATE OR REPLACE FUNCTION ml.nearby_category_competition(
    p_lon DOUBLE PRECISION,
    p_lat DOUBLE PRECISION,
    p_category TEXT,
    p_radius_m DOUBLE PRECISION DEFAULT 500
)
RETURNS BIGINT
LANGUAGE SQL
STABLE
AS $$
    SELECT COUNT(*)::BIGINT
    FROM curated.osm_poi_features p
    WHERE p.category_key = p_category
      AND ST_DWithin(
        p.geom::geography,
        ST_SetSRID(ST_MakePoint(p_lon, p_lat), 4326)::geography,
        p_radius_m
      );
$$;

CREATE OR REPLACE FUNCTION ml.get_ml_prediction_near(
    p_lon DOUBLE PRECISION,
    p_lat DOUBLE PRECISION,
    p_category TEXT DEFAULT 'salon'
)
RETURNS TABLE(
    grid_id TEXT,
    business_category TEXT,
    opportunity_score DOUBLE PRECISION,
    opportunity_rank DOUBLE PRECISION,
    demand_score DOUBLE PRECISION,
    accessibility_score DOUBLE PRECISION,
    commercial_activity_score DOUBLE PRECISION,
    competition_pressure DOUBLE PRECISION,
    confidence_score DOUBLE PRECISION,
    opportunity_type TEXT,
    distance_m DOUBLE PRECISION,
    explanation JSONB,
    model_version_id BIGINT
)
LANGUAGE SQL
STABLE
AS $$
    SELECT
        p.grid_id,
        p.business_category,
        p.opportunity_score,
        p.opportunity_rank,
        p.demand_score,
        p.accessibility_score,
        p.commercial_activity_score,
        p.competition_pressure,
        p.confidence_score,
        p.opportunity_type,
        ST_Distance(p.geom::geography, ST_SetSRID(ST_MakePoint(p_lon, p_lat), 4326)::geography)::DOUBLE PRECISION AS distance_m,
        p.explanation,
        p.model_version_id
    FROM ml.ml_opportunity_predictions p
    WHERE p.business_category = p_category
    ORDER BY p.geom <-> ST_SetSRID(ST_MakePoint(p_lon, p_lat), 4326)
    LIMIT 1;
$$;
