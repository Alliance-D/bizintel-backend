-- Phase 6: Real dataset integration + live opportunity cache
-- Apply after 009_tile_functions.sql.

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS geo;
CREATE SCHEMA IF NOT EXISTS curated;
CREATE SCHEMA IF NOT EXISTS ml;

CREATE TABLE IF NOT EXISTS raw.dataset_ingestion_runs (
    id BIGSERIAL PRIMARY KEY,
    dataset_key TEXT NOT NULL,
    source_file TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'started',
    row_count BIGINT DEFAULT 0,
    notes TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS raw.boundary_attributes (
    id BIGSERIAL PRIMARY KEY,
    boundary_level TEXT NOT NULL,
    province TEXT,
    district TEXT,
    sector TEXT,
    cell TEXT,
    village TEXT,
    source_row JSONB NOT NULL,
    source_file TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_boundary_attributes_level ON raw.boundary_attributes(boundary_level);
CREATE INDEX IF NOT EXISTS idx_boundary_attributes_names ON raw.boundary_attributes(province, district, sector, cell, village);

CREATE TABLE IF NOT EXISTS geo.population_density_grid (
    id BIGSERIAL PRIMARY KEY,
    density DOUBLE PRECISION NOT NULL,
    geom geometry(Point, 4326) NOT NULL,
    source_file TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_population_density_grid_geom ON geo.population_density_grid USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_population_density_grid_density ON geo.population_density_grid(density);

CREATE TABLE IF NOT EXISTS curated.sector_population_features (
    id BIGSERIAL PRIMARY KEY,
    province TEXT,
    district TEXT,
    sector TEXT,
    sector_id TEXT,
    period INTEGER,
    male_population DOUBLE PRECISION,
    female_population DOUBLE PRECISION,
    total_population DOUBLE PRECISION,
    female_share DOUBLE PRECISION,
    male_share DOUBLE PRECISION,
    source_file TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_sector_population_features ON curated.sector_population_features(COALESCE(sector_id,''), COALESCE(sector,''), COALESCE(district,''), COALESCE(period,0));
CREATE INDEX IF NOT EXISTS idx_sector_population_features_names ON curated.sector_population_features(district, sector, period);

CREATE TABLE IF NOT EXISTS curated.movement_features (
    id BIGSERIAL PRIMARY KEY,
    country TEXT,
    gadm_id TEXT,
    gadm_name TEXT,
    polygon_level TEXT,
    distance_category TEXT,
    distance_fraction DOUBLE PRECISION,
    observation_date DATE,
    source_file TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_movement_features_area ON curated.movement_features(gadm_name, observation_date);

CREATE TABLE IF NOT EXISTS curated.lfs_district_features (
    id BIGSERIAL PRIMARY KEY,
    district TEXT,
    province TEXT,
    urban_rural TEXT,
    employment_rate DOUBLE PRECISION,
    unemployment_rate DOUBLE PRECISION,
    youth_unemployment_rate DOUBLE PRECISION,
    labour_force_participation DOUBLE PRECISION,
    income_proxy DOUBLE PRECISION,
    formal_employment_share DOUBLE PRECISION,
    informal_employment_share DOUBLE PRECISION,
    source_file TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_lfs_district_features_district ON curated.lfs_district_features(district);

CREATE TABLE IF NOT EXISTS curated.establishment_area_features (
    id BIGSERIAL PRIMARY KEY,
    province TEXT,
    district TEXT,
    sector TEXT,
    business_category TEXT,
    establishment_count INTEGER DEFAULT 0,
    total_workers DOUBLE PRECISION,
    avg_workers DOUBLE PRECISION,
    informal_share DOUBLE PRECISION,
    turnover_proxy DOUBLE PRECISION,
    source_file TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_establishment_area_features_area ON curated.establishment_area_features(district, sector, business_category);

CREATE TABLE IF NOT EXISTS ml.live_location_context_logs (
    id BIGSERIAL PRIMARY KEY,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    business_category TEXT NOT NULL,
    request_payload JSONB,
    response_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ml.live_opportunity_cache (
    id BIGSERIAL PRIMARY KEY,
    grid_id TEXT NOT NULL,
    business_category TEXT NOT NULL,
    opportunity_score DOUBLE PRECISION NOT NULL,
    demand_score DOUBLE PRECISION NOT NULL,
    competition_score DOUBLE PRECISION NOT NULL,
    access_score DOUBLE PRECISION NOT NULL,
    commercial_activity_score DOUBLE PRECISION NOT NULL,
    confidence_score DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    opportunity_type TEXT,
    dominant_factor TEXT,
    explanation JSONB DEFAULT '{}'::jsonb,
    geom geometry(Point, 4326) NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    model_version_id BIGINT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_live_opportunity_cache ON ml.live_opportunity_cache(grid_id, business_category);
CREATE INDEX IF NOT EXISTS idx_live_opportunity_cache_geom ON ml.live_opportunity_cache USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_live_opportunity_cache_category_score ON ml.live_opportunity_cache(business_category, opportunity_score DESC);

CREATE OR REPLACE VIEW curated.data_readiness_summary AS
SELECT 'population_density_grid' AS layer, COUNT(*)::BIGINT AS rows, MAX(created_at) AS last_loaded FROM geo.population_density_grid
UNION ALL
SELECT 'sector_population_features', COUNT(*)::BIGINT, MAX(created_at) FROM curated.sector_population_features
UNION ALL
SELECT 'movement_features', COUNT(*)::BIGINT, MAX(created_at) FROM curated.movement_features
UNION ALL
SELECT 'lfs_district_features', COUNT(*)::BIGINT, MAX(created_at) FROM curated.lfs_district_features
UNION ALL
SELECT 'establishment_area_features', COUNT(*)::BIGINT, MAX(created_at) FROM curated.establishment_area_features
UNION ALL
SELECT 'live_opportunity_cache', COUNT(*)::BIGINT, MAX(generated_at) FROM ml.live_opportunity_cache;

CREATE OR REPLACE FUNCTION ml.get_population_density_near(p_lon DOUBLE PRECISION, p_lat DOUBLE PRECISION, p_radius_m DOUBLE PRECISION DEFAULT 1000)
RETURNS TABLE(avg_density DOUBLE PRECISION, max_density DOUBLE PRECISION, sample_count BIGINT)
LANGUAGE SQL
STABLE
AS $$
    SELECT
        AVG(density)::DOUBLE PRECISION AS avg_density,
        MAX(density)::DOUBLE PRECISION AS max_density,
        COUNT(*)::BIGINT AS sample_count
    FROM geo.population_density_grid
    WHERE ST_DWithin(
        geom::geography,
        ST_SetSRID(ST_MakePoint(p_lon, p_lat), 4326)::geography,
        p_radius_m
    );
$$;

CREATE OR REPLACE FUNCTION ml.get_nearest_live_opportunity(p_lon DOUBLE PRECISION, p_lat DOUBLE PRECISION, p_category TEXT DEFAULT 'salon')
RETURNS TABLE(
    grid_id TEXT,
    business_category TEXT,
    opportunity_score DOUBLE PRECISION,
    demand_score DOUBLE PRECISION,
    competition_score DOUBLE PRECISION,
    access_score DOUBLE PRECISION,
    commercial_activity_score DOUBLE PRECISION,
    confidence_score DOUBLE PRECISION,
    opportunity_type TEXT,
    distance_m DOUBLE PRECISION,
    explanation JSONB
)
LANGUAGE SQL
STABLE
AS $$
    SELECT
        c.grid_id,
        c.business_category,
        c.opportunity_score,
        c.demand_score,
        c.competition_score,
        c.access_score,
        c.commercial_activity_score,
        c.confidence_score,
        c.opportunity_type,
        ST_Distance(c.geom::geography, ST_SetSRID(ST_MakePoint(p_lon, p_lat), 4326)::geography)::DOUBLE PRECISION AS distance_m,
        c.explanation
    FROM ml.live_opportunity_cache c
    WHERE c.business_category = p_category
    ORDER BY c.geom <-> ST_SetSRID(ST_MakePoint(p_lon, p_lat), 4326)
    LIMIT 1;
$$;
