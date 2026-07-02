-- Phase 2: Spatial data warehouse and feature-generation foundations.
-- Run after 001_init_schemas.sql.

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE SCHEMA IF NOT EXISTS meta;
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS geo;
CREATE SCHEMA IF NOT EXISTS curated;
CREATE SCHEMA IF NOT EXISTS field;
CREATE SCHEMA IF NOT EXISTS ml;
CREATE SCHEMA IF NOT EXISTS app;

-- -----------------------------------------------------------------------------
-- Metadata catalog
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS meta.dataset_catalog (
    id BIGSERIAL PRIMARY KEY,
    dataset_key TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    owner TEXT,
    source_url TEXT,
    license_status TEXT DEFAULT 'unknown',
    permission_status TEXT DEFAULT 'not_confirmed',
    spatial_level TEXT,
    update_frequency TEXT,
    raw_storage_path TEXT,
    recommended_layer TEXT,
    relevance TEXT,
    rows_estimate BIGINT,
    columns_count INT,
    size_mb NUMERIC(12,2),
    imported_at TIMESTAMPTZ,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS meta.variable_catalog (
    id BIGSERIAL PRIMARY KEY,
    dataset_key TEXT NOT NULL,
    variable_name TEXT NOT NULL,
    variable_label TEXT,
    data_type TEXT,
    geographic_level TEXT,
    recommended_use TEXT DEFAULT 'inspect',
    feature_candidate BOOLEAN DEFAULT false,
    privacy_risk TEXT DEFAULT 'unknown',
    notes TEXT,
    UNIQUE(dataset_key, variable_name)
);

CREATE TABLE IF NOT EXISTS meta.feature_catalog (
    id BIGSERIAL PRIMARY KEY,
    feature_name TEXT UNIQUE NOT NULL,
    feature_group TEXT NOT NULL,
    source_layer TEXT NOT NULL,
    geographic_level TEXT NOT NULL,
    business_category_specific BOOLEAN DEFAULT false,
    used_for_training BOOLEAN DEFAULT true,
    used_for_prediction BOOLEAN DEFAULT true,
    calculation_method TEXT NOT NULL,
    interpretation TEXT NOT NULL,
    quality_risk TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- Administrative layers
-- CSV files from some portals may only include attributes. Geometry should be
-- loaded from GeoJSON/Shapefile/WKT-enabled exports when available.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS geo.provinces (
    province_id TEXT PRIMARY KEY,
    province_name TEXT NOT NULL,
    area_m2 NUMERIC,
    geom geometry(MultiPolygon, 4326)
);

CREATE TABLE IF NOT EXISTS geo.districts (
    district_id TEXT PRIMARY KEY,
    province_id TEXT,
    province_name TEXT,
    district_name TEXT NOT NULL,
    area_m2 NUMERIC,
    geom geometry(MultiPolygon, 4326)
);

CREATE TABLE IF NOT EXISTS geo.sectors (
    sector_id TEXT PRIMARY KEY,
    district_id TEXT,
    province_name TEXT,
    district_name TEXT,
    sector_name TEXT NOT NULL,
    area_m2 NUMERIC,
    geom geometry(MultiPolygon, 4326)
);

CREATE TABLE IF NOT EXISTS geo.cells (
    cell_id TEXT PRIMARY KEY,
    sector_id TEXT,
    district_id TEXT,
    province_name TEXT,
    district_name TEXT,
    sector_name TEXT,
    cell_name TEXT NOT NULL,
    area_m2 NUMERIC,
    geom geometry(MultiPolygon, 4326)
);

CREATE TABLE IF NOT EXISTS geo.villages (
    village_id TEXT PRIMARY KEY,
    cell_id TEXT,
    sector_id TEXT,
    district_id TEXT,
    province_name TEXT,
    district_name TEXT,
    sector_name TEXT,
    cell_name TEXT,
    village_name TEXT NOT NULL,
    area_m2 NUMERIC,
    geom geometry(MultiPolygon, 4326)
);

CREATE INDEX IF NOT EXISTS idx_geo_provinces_geom ON geo.provinces USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_geo_districts_geom ON geo.districts USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_geo_sectors_geom ON geo.sectors USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_geo_cells_geom ON geo.cells USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_geo_villages_geom ON geo.villages USING GIST (geom);

-- -----------------------------------------------------------------------------
-- Population raster and analysis grid
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS geo.population_density_grid (
    id BIGSERIAL PRIMARY KEY,
    density DOUBLE PRECISION NOT NULL,
    source_year INT DEFAULT 2020,
    geom geometry(Point, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_population_density_grid_geom ON geo.population_density_grid USING GIST (geom);

CREATE TABLE IF NOT EXISTS geo.analysis_grid (
    grid_id TEXT PRIMARY KEY,
    grid_size_m INT NOT NULL DEFAULT 250,
    district_name TEXT,
    sector_name TEXT,
    cell_name TEXT,
    geom geometry(Polygon, 4326) NOT NULL,
    centroid geometry(Point, 4326) GENERATED ALWAYS AS (ST_Centroid(geom)) STORED,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_analysis_grid_geom ON geo.analysis_grid USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_analysis_grid_centroid ON geo.analysis_grid USING GIST (centroid);

-- -----------------------------------------------------------------------------
-- OSM/general spatial layers. These are normalized layers created from osm2pgsql
-- output, not raw planet tables.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS geo.osm_pois (
    id BIGSERIAL PRIMARY KEY,
    osm_id TEXT,
    name TEXT,
    category TEXT,
    subcategory TEXT,
    tags JSONB,
    geom geometry(Point, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_osm_pois_geom ON geo.osm_pois USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_osm_pois_category ON geo.osm_pois (category, subcategory);

CREATE TABLE IF NOT EXISTS geo.osm_roads (
    id BIGSERIAL PRIMARY KEY,
    osm_id TEXT,
    name TEXT,
    road_class TEXT,
    road_score NUMERIC(5,2),
    tags JSONB,
    geom geometry(LineString, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_osm_roads_geom ON geo.osm_roads USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_osm_roads_class ON geo.osm_roads (road_class);

CREATE TABLE IF NOT EXISTS geo.osm_buildings (
    id BIGSERIAL PRIMARY KEY,
    osm_id TEXT,
    building_type TEXT,
    tags JSONB,
    geom geometry(Polygon, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_osm_buildings_geom ON geo.osm_buildings USING GIST (geom);

-- -----------------------------------------------------------------------------
-- Curated area-level feature tables
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS curated.sector_population_features (
    sector_id TEXT PRIMARY KEY,
    sector_name TEXT,
    district_name TEXT,
    population_2022 BIGINT,
    population_2012 BIGINT,
    population_growth_2012_2022 NUMERIC(10,4),
    female_share_2022 NUMERIC(10,4),
    male_share_2022 NUMERIC(10,4),
    source_dataset TEXT,
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS curated.district_lfs_features (
    district_name TEXT PRIMARY KEY,
    employment_rate NUMERIC(10,4),
    unemployment_rate NUMERIC(10,4),
    youth_unemployment_rate NUMERIC(10,4),
    labour_force_participation_rate NUMERIC(10,4),
    income_proxy NUMERIC(12,2),
    informal_employment_share NUMERIC(10,4),
    source_dataset TEXT,
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS curated.establishment_area_features (
    area_key TEXT NOT NULL,
    area_level TEXT NOT NULL,
    business_category TEXT NOT NULL,
    establishment_count BIGINT DEFAULT 0,
    avg_workers NUMERIC(12,2),
    formal_share NUMERIC(10,4),
    informal_share NUMERIC(10,4),
    avg_turnover_proxy NUMERIC(14,2),
    business_density_score NUMERIC(10,4),
    source_dataset TEXT,
    updated_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (area_key, area_level, business_category)
);

CREATE TABLE IF NOT EXISTS curated.welfare_area_features (
    area_key TEXT NOT NULL,
    area_level TEXT NOT NULL,
    poverty_proxy NUMERIC(10,4),
    welfare_index NUMERIC(10,4),
    expenditure_proxy NUMERIC(14,2),
    service_access_index NUMERIC(10,4),
    rent_proxy NUMERIC(14,2),
    source_dataset TEXT,
    updated_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (area_key, area_level)
);

CREATE TABLE IF NOT EXISTS curated.mobility_features (
    district_name TEXT NOT NULL,
    date_start DATE,
    date_end DATE,
    local_mobility_share NUMERIC(10,4),
    medium_distance_share NUMERIC(10,4),
    long_distance_share NUMERIC(10,4),
    source_dataset TEXT,
    updated_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (district_name, date_start, date_end)
);

-- -----------------------------------------------------------------------------
-- Training/prediction features. One row = grid cell + business category.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ml.category_profiles (
    business_category TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    demand_weight NUMERIC(6,3) DEFAULT 0.30,
    access_weight NUMERIC(6,3) DEFAULT 0.25,
    commercial_weight NUMERIC(6,3) DEFAULT 0.20,
    competition_weight NUMERIC(6,3) DEFAULT 0.15,
    welfare_weight NUMERIC(6,3) DEFAULT 0.10,
    confidence_level TEXT DEFAULT 'medium',
    notes TEXT
);

CREATE TABLE IF NOT EXISTS ml.training_features (
    id BIGSERIAL PRIMARY KEY,
    grid_id TEXT NOT NULL REFERENCES geo.analysis_grid(grid_id) ON DELETE CASCADE,
    business_category TEXT NOT NULL,
    demand_score NUMERIC(10,4),
    population_density_500m NUMERIC(14,4),
    population_density_1000m NUMERIC(14,4),
    sector_population BIGINT,
    female_share NUMERIC(10,4),
    youth_share NUMERIC(10,4),
    access_score NUMERIC(10,4),
    nearest_main_road_m NUMERIC(14,4),
    bus_stop_count_500m INT,
    market_distance_m NUMERIC(14,4),
    commercial_activity_score NUMERIC(10,4),
    commercial_poi_count_500m INT,
    competitor_count_300m INT,
    competitor_count_500m INT,
    competitor_count_1000m INT,
    business_density_area NUMERIC(10,4),
    welfare_index NUMERIC(10,4),
    income_proxy NUMERIC(14,2),
    opportunity_gap_score NUMERIC(10,4),
    target_presence INT,
    target_business_count INT,
    generated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(grid_id, business_category)
);
CREATE INDEX IF NOT EXISTS idx_training_features_category ON ml.training_features (business_category);
CREATE INDEX IF NOT EXISTS idx_training_features_grid ON ml.training_features (grid_id);

CREATE TABLE IF NOT EXISTS ml.opportunity_predictions (
    id BIGSERIAL PRIMARY KEY,
    grid_id TEXT NOT NULL REFERENCES geo.analysis_grid(grid_id) ON DELETE CASCADE,
    business_category TEXT NOT NULL,
    model_version TEXT,
    opportunity_score NUMERIC(10,4),
    demand_score NUMERIC(10,4),
    competition_pressure NUMERIC(10,4),
    access_score NUMERIC(10,4),
    commercial_activity_score NUMERIC(10,4),
    confidence_score NUMERIC(10,4),
    opportunity_type TEXT,
    predicted_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(grid_id, business_category, model_version)
);
CREATE INDEX IF NOT EXISTS idx_opportunity_predictions_category_score ON ml.opportunity_predictions (business_category, opportunity_score DESC);
