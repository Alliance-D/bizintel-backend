from __future__ import annotations

PHASE27_DATA_LAYER_SQL = r"""
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS geo;
CREATE SCHEMA IF NOT EXISTS curated;
CREATE SCHEMA IF NOT EXISTS ml;
CREATE SCHEMA IF NOT EXISTS app;
CREATE SCHEMA IF NOT EXISTS field;

-- Category profile is the central source of truth for the product and model.
CREATE TABLE IF NOT EXISTS curated.business_category_profiles (
  category_key TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  display_name_rw TEXT,
  description TEXT,
  description_rw TEXT,
  osm_filter JSONB NOT NULL DEFAULT '[]'::jsonb,
  demand_weight DOUBLE PRECISION NOT NULL DEFAULT 0.30,
  access_weight DOUBLE PRECISION NOT NULL DEFAULT 0.20,
  commercial_weight DOUBLE PRECISION NOT NULL DEFAULT 0.20,
  competition_weight DOUBLE PRECISION NOT NULL DEFAULT 0.20,
  welfare_weight DOUBLE PRECISION NOT NULL DEFAULT 0.10,
  min_confidence_threshold INTEGER NOT NULL DEFAULT 50,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Raw import log for traceability.
CREATE TABLE IF NOT EXISTS raw.dataset_imports (
  id BIGSERIAL PRIMARY KEY,
  dataset_key TEXT NOT NULL,
  source_path TEXT,
  source_owner TEXT,
  license_status TEXT,
  permission_status TEXT,
  rows_imported BIGINT DEFAULT 0,
  import_status TEXT NOT NULL DEFAULT 'pending',
  message TEXT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS geo.admin_boundaries (
  id BIGSERIAL PRIMARY KEY,
  boundary_level TEXT NOT NULL,
  province TEXT,
  district TEXT,
  sector TEXT,
  cell TEXT,
  village TEXT,
  source_id TEXT,
  geom geometry(MultiPolygon, 4326),
  attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_admin_boundaries_geom ON geo.admin_boundaries USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_admin_boundaries_lookup ON geo.admin_boundaries (boundary_level, district, sector, cell);

-- Analysis grid. H3 extension is not required; this stores PostGIS generated hex cells.
CREATE TABLE IF NOT EXISTS geo.analysis_grid (
  grid_id TEXT PRIMARY KEY,
  cell_radius_m INTEGER NOT NULL DEFAULT 500,
  geom geometry(Polygon, 4326) NOT NULL,
  centroid geometry(Point, 4326) NOT NULL,
  district TEXT,
  sector TEXT,
  cell TEXT,
  data_coverage JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_analysis_grid_geom ON geo.analysis_grid USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_analysis_grid_centroid ON geo.analysis_grid USING GIST (centroid);
CREATE INDEX IF NOT EXISTS idx_analysis_grid_admin ON geo.analysis_grid (district, sector, cell);

-- Population density points from WorldPop or similar 1km raster-derived CSV.
CREATE TABLE IF NOT EXISTS curated.population_density_points (
  id BIGSERIAL PRIMARY KEY,
  source_key TEXT NOT NULL DEFAULT 'population_density',
  population_density DOUBLE PRECISION NOT NULL,
  geom geometry(Point, 4326) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_population_density_geom ON curated.population_density_points USING GIST (geom);

CREATE TABLE IF NOT EXISTS curated.population_count_features (
  id BIGSERIAL PRIMARY KEY,
  province TEXT,
  district TEXT,
  sector TEXT,
  sector_id TEXT,
  male BIGINT,
  female BIGINT,
  total_population BIGINT,
  period INTEGER,
  attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_population_count_sector ON curated.population_count_features (district, sector, period);

-- OSM POIs and businesses normalized into product categories and support layers.
CREATE TABLE IF NOT EXISTS curated.osm_poi_features (
  id BIGSERIAL PRIMARY KEY,
  osm_id TEXT,
  name TEXT,
  category_key TEXT NOT NULL,
  primary_key TEXT,
  primary_value TEXT,
  tags JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_layer TEXT,
  geom geometry(Point, 4326) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_osm_poi_geom ON curated.osm_poi_features USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_osm_poi_category ON curated.osm_poi_features (category_key);
CREATE UNIQUE INDEX IF NOT EXISTS idx_osm_poi_unique_osm_category ON curated.osm_poi_features (COALESCE(osm_id,''), category_key, COALESCE(name,''));

-- Establishment census features should be aggregated to district, sector or cell before training.
CREATE TABLE IF NOT EXISTS curated.establishment_area_features (
  id BIGSERIAL PRIMARY KEY,
  area_level TEXT NOT NULL DEFAULT 'sector',
  district TEXT,
  sector TEXT,
  cell TEXT,
  business_category TEXT NOT NULL,
  establishment_count BIGINT DEFAULT 0,
  worker_count BIGINT,
  formal_count BIGINT,
  informal_count BIGINT,
  turnover_proxy DOUBLE PRECISION,
  attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_establishment_area_lookup ON curated.establishment_area_features (area_level, district, sector, cell, business_category);

-- Field validation is stored separately from training labels. It validates and calibrates.
CREATE TABLE IF NOT EXISTS field.validation_points (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT,
  business_category TEXT NOT NULL,
  latitude DOUBLE PRECISION NOT NULL,
  longitude DOUBLE PRECISION NOT NULL,
  geom geometry(Point, 4326),
  observed_activity TEXT,
  pedestrian_level TEXT,
  visible_competitors INTEGER DEFAULT 0,
  informal_competitors INTEGER DEFAULT 0,
  visibility_score INTEGER,
  rent_signal TEXT,
  model_score DOUBLE PRECISION,
  model_label TEXT,
  validator_notes TEXT,
  photo_url TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_validation_points_geom ON field.validation_points USING GIST (geom);

-- One row per grid cell and business category. This is the ML training and prediction input.
CREATE TABLE IF NOT EXISTS ml.grid_category_features (
  id BIGSERIAL PRIMARY KEY,
  grid_id TEXT NOT NULL REFERENCES geo.analysis_grid(grid_id) ON DELETE CASCADE,
  business_category TEXT NOT NULL,
  geom geometry(Polygon, 4326),
  centroid geometry(Point, 4326),
  district TEXT,
  sector TEXT,
  cell TEXT,
  population_density_500m DOUBLE PRECISION DEFAULT 0,
  population_density_1000m DOUBLE PRECISION DEFAULT 0,
  sector_population DOUBLE PRECISION DEFAULT 0,
  employment_rate DOUBLE PRECISION DEFAULT 0,
  income_proxy DOUBLE PRECISION DEFAULT 0,
  welfare_proxy DOUBLE PRECISION DEFAULT 0,
  competitor_count_300m INTEGER DEFAULT 0,
  competitor_count_500m INTEGER DEFAULT 0,
  competitor_count_1000m INTEGER DEFAULT 0,
  nearest_competitor_m DOUBLE PRECISION,
  complementary_poi_count_500m INTEGER DEFAULT 0,
  commercial_poi_count_500m INTEGER DEFAULT 0,
  demand_generator_count_1000m INTEGER DEFAULT 0,
  market_distance_m DOUBLE PRECISION,
  school_count_1000m INTEGER DEFAULT 0,
  health_facility_count_1000m INTEGER DEFAULT 0,
  bus_stop_count_500m INTEGER DEFAULT 0,
  nearest_bus_stop_m DOUBLE PRECISION,
  establishment_category_count_area DOUBLE PRECISION DEFAULT 0,
  establishment_density_area DOUBLE PRECISION DEFAULT 0,
  demand_score DOUBLE PRECISION DEFAULT 0,
  accessibility_score DOUBLE PRECISION DEFAULT 0,
  commercial_activity_score DOUBLE PRECISION DEFAULT 0,
  competition_pressure DOUBLE PRECISION DEFAULT 0,
  welfare_score DOUBLE PRECISION DEFAULT 0,
  opportunity_gap_score DOUBLE PRECISION DEFAULT 0,
  confidence_score DOUBLE PRECISION DEFAULT 0,
  presence_target INTEGER DEFAULT 0,
  business_count_target DOUBLE PRECISION DEFAULT 0,
  ranking_relevance DOUBLE PRECISION DEFAULT 0,
  feature_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(grid_id, business_category)
);
CREATE INDEX IF NOT EXISTS idx_grid_category_features_centroid ON ml.grid_category_features USING GIST (centroid);
CREATE INDEX IF NOT EXISTS idx_grid_category_features_category ON ml.grid_category_features (business_category);

CREATE TABLE IF NOT EXISTS ml.model_versions (
  id BIGSERIAL PRIMARY KEY,
  model_name TEXT NOT NULL,
  business_category TEXT,
  target_name TEXT NOT NULL DEFAULT 'opportunity_gap_score',
  algorithm TEXT NOT NULL,
  artifact_path TEXT,
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  feature_columns TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  is_active BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_model_versions_active ON ml.model_versions (business_category, is_active);

CREATE TABLE IF NOT EXISTS ml.ml_opportunity_predictions (
  id BIGSERIAL PRIMARY KEY,
  grid_id TEXT NOT NULL,
  business_category TEXT NOT NULL,
  model_version_id BIGINT,
  opportunity_score DOUBLE PRECISION NOT NULL,
  demand_score DOUBLE PRECISION DEFAULT 0,
  accessibility_score DOUBLE PRECISION DEFAULT 0,
  commercial_activity_score DOUBLE PRECISION DEFAULT 0,
  competition_pressure DOUBLE PRECISION DEFAULT 0,
  confidence_score DOUBLE PRECISION DEFAULT 0,
  opportunity_rank INTEGER,
  opportunity_type TEXT,
  zone_key TEXT,
  risk_level TEXT,
  explanation JSONB NOT NULL DEFAULT '{}'::jsonb,
  geom geometry(Point, 4326) NOT NULL,
  cell_geom geometry(Polygon, 4326),
  district TEXT,
  sector TEXT,
  cell TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ml_predictions_unique_grid_category_model
ON ml.ml_opportunity_predictions (grid_id, business_category, (COALESCE(model_version_id, 0)));
CREATE INDEX IF NOT EXISTS idx_ml_predictions_geom ON ml.ml_opportunity_predictions USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_ml_predictions_category_score ON ml.ml_opportunity_predictions (business_category, opportunity_score DESC);

CREATE TABLE IF NOT EXISTS app.tutorial_progress (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT,
  tutorial_key TEXT NOT NULL DEFAULT 'first_visit',
  locale TEXT NOT NULL DEFAULT 'en',
  completed BOOLEAN NOT NULL DEFAULT FALSE,
  completed_at TIMESTAMPTZ,
  last_step INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);


CREATE TABLE IF NOT EXISTS app.saved_locations (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT,
  name TEXT NOT NULL DEFAULT 'Saved location',
  business_category TEXT NOT NULL,
  latitude DOUBLE PRECISION NOT NULL,
  longitude DOUBLE PRECISION NOT NULL,
  geom geometry(Point, 4326),
  opportunity_score DOUBLE PRECISION,
  risk_level TEXT,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_saved_locations_geom ON app.saved_locations USING GIST (geom);



-- Idempotent column upgrades for databases created by earlier phases.
ALTER TABLE field.validation_points ADD COLUMN IF NOT EXISTS geom geometry(Point, 4326);
ALTER TABLE field.validation_points ADD COLUMN IF NOT EXISTS informal_competitors INTEGER DEFAULT 0;
ALTER TABLE field.validation_points ADD COLUMN IF NOT EXISTS visibility_score INTEGER;
ALTER TABLE field.validation_points ADD COLUMN IF NOT EXISTS rent_signal TEXT;
UPDATE field.validation_points SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326) WHERE geom IS NULL AND longitude IS NOT NULL AND latitude IS NOT NULL;

ALTER TABLE app.saved_locations ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE ml.ml_opportunity_predictions ADD COLUMN IF NOT EXISTS cell_geom geometry(Polygon, 4326);
ALTER TABLE ml.ml_opportunity_predictions ADD COLUMN IF NOT EXISTS zone_key TEXT;
ALTER TABLE ml.ml_opportunity_predictions ADD COLUMN IF NOT EXISTS risk_level TEXT;
ALTER TABLE ml.ml_opportunity_predictions ADD COLUMN IF NOT EXISTS district TEXT;
ALTER TABLE ml.ml_opportunity_predictions ADD COLUMN IF NOT EXISTS sector TEXT;
ALTER TABLE ml.ml_opportunity_predictions ADD COLUMN IF NOT EXISTS cell TEXT;

CREATE OR REPLACE FUNCTION curated.score_from_count(value DOUBLE PRECISION, high_value DOUBLE PRECISION)
RETURNS DOUBLE PRECISION AS $$
BEGIN
  IF high_value IS NULL OR high_value <= 0 THEN
    RETURN 0;
  END IF;
  RETURN LEAST(100, GREATEST(0, (COALESCE(value, 0) / high_value) * 100));
END;
$$ LANGUAGE plpgsql IMMUTABLE;

CREATE OR REPLACE FUNCTION curated.distance_score(distance_m DOUBLE PRECISION, good_m DOUBLE PRECISION, poor_m DOUBLE PRECISION)
RETURNS DOUBLE PRECISION AS $$
BEGIN
  IF distance_m IS NULL THEN
    RETURN 0;
  END IF;
  IF distance_m <= good_m THEN
    RETURN 100;
  END IF;
  IF distance_m >= poor_m THEN
    RETURN 0;
  END IF;
  RETURN GREATEST(0, LEAST(100, 100 * (poor_m - distance_m) / NULLIF((poor_m - good_m), 0)));
END;
$$ LANGUAGE plpgsql IMMUTABLE;

CREATE OR REPLACE FUNCTION ml.get_ml_prediction_near(p_lon DOUBLE PRECISION, p_lat DOUBLE PRECISION, p_category TEXT)
RETURNS TABLE (
  grid_id TEXT,
  business_category TEXT,
  opportunity_score DOUBLE PRECISION,
  demand_score DOUBLE PRECISION,
  accessibility_score DOUBLE PRECISION,
  commercial_activity_score DOUBLE PRECISION,
  competition_pressure DOUBLE PRECISION,
  confidence_score DOUBLE PRECISION,
  opportunity_rank INTEGER,
  opportunity_type TEXT,
  zone_key TEXT,
  risk_level TEXT,
  explanation JSONB,
  model_version_id BIGINT,
  distance_m DOUBLE PRECISION,
  geom geometry(Point, 4326),
  district TEXT,
  sector TEXT,
  cell TEXT
) AS $$
BEGIN
  RETURN QUERY
  SELECT
    p.grid_id, p.business_category, p.opportunity_score, p.demand_score,
    p.accessibility_score, p.commercial_activity_score, p.competition_pressure,
    p.confidence_score, p.opportunity_rank, p.opportunity_type, p.zone_key,
    p.risk_level, p.explanation, p.model_version_id,
    ST_Distance(p.geom::geography, ST_SetSRID(ST_MakePoint(p_lon, p_lat), 4326)::geography) AS distance_m,
    p.geom, p.district, p.sector, p.cell
  FROM ml.ml_opportunity_predictions p
  WHERE p.business_category = p_category
  ORDER BY p.geom <-> ST_SetSRID(ST_MakePoint(p_lon, p_lat), 4326)
  LIMIT 1;
END;
$$ LANGUAGE plpgsql STABLE;

-- Seed priority categories. No blue/product styling is involved; these are data semantics.
INSERT INTO curated.business_category_profiles (
  category_key, display_name, display_name_rw, description, description_rw, osm_filter,
  demand_weight, access_weight, commercial_weight, competition_weight, welfare_weight, min_confidence_threshold, is_active
) VALUES
('pharmacy','Pharmacy','Farumasi','Medicine access and health retail locations','Aho serivisi za farumasi n’imiti byoroshye kugerwaho','[{"key":"amenity","value":"pharmacy"},{"key":"healthcare","value":"pharmacy"}]',0.30,0.28,0.18,0.16,0.08,60,TRUE),
('restaurant','Restaurant and fast food','Resitora n’aho bagurisha ibiryo byihuse','Food service, restaurants and fast food businesses','Ubucuruzi bwa resitora n’ahagurishirizwa ibiryo byihuse','[{"key":"amenity","value":"restaurant"},{"key":"amenity","value":"fast_food"},{"key":"amenity","value":"food_court"}]',0.25,0.24,0.31,0.12,0.08,58,TRUE),
('cafe','Café','Kafe','Coffee, snack, study and social meeting places','Aho kunywera ikawa, gufata utuntu, kwiga cyangwa guhurira','[{"key":"amenity","value":"cafe"}]',0.22,0.22,0.34,0.14,0.08,55,TRUE),
('grocery','Supermarket and grocery','Supamaketi n’iduka ry’ibiribwa','Daily household goods, supermarkets and grocery stores','Amaduka y’ibiribwa n’ibikoresho byo mu rugo bya buri munsi','[{"key":"shop","value":"supermarket"},{"key":"shop","value":"grocery"},{"key":"shop","value":"convenience"},{"key":"shop","value":"greengrocer"}]',0.39,0.20,0.16,0.17,0.08,55,TRUE),
('salon','Salon and personal care','Saloon n’ubwiza','Hair, beauty, barbering and personal care services','Serivisi z’imisatsi, ubwiza, kogosha n’isuku y’umuntu','[{"key":"shop","value":"hairdresser"},{"key":"shop","value":"beauty"},{"key":"shop","value":"cosmetics"},{"key":"amenity","value":"barber"}]',0.34,0.20,0.22,0.16,0.08,45,TRUE)
ON CONFLICT (category_key) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  display_name_rw = EXCLUDED.display_name_rw,
  description = EXCLUDED.description,
  description_rw = EXCLUDED.description_rw,
  osm_filter = EXCLUDED.osm_filter,
  demand_weight = EXCLUDED.demand_weight,
  access_weight = EXCLUDED.access_weight,
  commercial_weight = EXCLUDED.commercial_weight,
  competition_weight = EXCLUDED.competition_weight,
  welfare_weight = EXCLUDED.welfare_weight,
  min_confidence_threshold = EXCLUDED.min_confidence_threshold,
  is_active = TRUE,
  updated_at = now();
"""
