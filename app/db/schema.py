"""The single source of truth for the application's PostgreSQL/PostGIS schema.

This SQL is applied by the Alembic baseline migration
(alembic/versions/0001_initial_schema.py), not run directly by the app at
startup. To change the schema, add a new Alembic migration rather than
editing this file after the baseline has been applied anywhere.
"""
from __future__ import annotations

CANONICAL_SCHEMA_SQL = r"""
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS geo;
CREATE SCHEMA IF NOT EXISTS curated;
CREATE SCHEMA IF NOT EXISTS ml;
CREATE SCHEMA IF NOT EXISTS app;
CREATE SCHEMA IF NOT EXISTS field;
CREATE SCHEMA IF NOT EXISTS meta;

-- ==================== meta: documentation for admin/methodology pages ====================

CREATE TABLE IF NOT EXISTS meta.feature_catalog (
  id BIGSERIAL PRIMARY KEY,
  feature_name TEXT NOT NULL UNIQUE,
  feature_group TEXT NOT NULL,
  source_layer TEXT NOT NULL,
  geographic_level TEXT NOT NULL,
  business_category_specific BOOLEAN NOT NULL DEFAULT FALSE,
  used_for_training BOOLEAN NOT NULL DEFAULT TRUE,
  used_for_prediction BOOLEAN NOT NULL DEFAULT TRUE,
  calculation_method TEXT NOT NULL,
  interpretation TEXT NOT NULL,
  quality_risk TEXT
);

-- ==================== raw: import provenance log ====================

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

-- ==================== geo: administrative boundaries and the analysis grid ====================

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

-- ==================== curated: cleaned, feature-ready data layers ====================

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

-- Establishment Census (NISR 2023), aggregated to district x ISIC-derived category.
-- District-level only - the source microdata has no sector/GPS field.
CREATE TABLE IF NOT EXISTS curated.establishment_area_features (
  id BIGSERIAL PRIMARY KEY,
  area_level TEXT NOT NULL DEFAULT 'district',
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

-- Sector-level (PHC5 2022 census) and district-level (LFS 2025 / VUP welfare
-- survey) demographic and welfare features. Two resolutions share one table
-- via area_level; grid feature generation prefers a sector match and falls
-- back to district.
CREATE TABLE IF NOT EXISTS curated.population_welfare_features (
  id BIGSERIAL PRIMARY KEY,
  area_level TEXT NOT NULL DEFAULT 'sector',
  district TEXT,
  sector TEXT,
  source TEXT NOT NULL,
  population_sample_size INTEGER,
  youth_share DOUBLE PRECISION,
  female_share DOUBLE PRECISION,
  working_age_share DOUBLE PRECISION,
  employment_rate DOUBLE PRECISION,
  electricity_access_share DOUBLE PRECISION,
  internet_access_share DOUBLE PRECISION,
  asset_welfare_index DOUBLE PRECISION,
  poverty_proxy DOUBLE PRECISION,
  income_proxy DOUBLE PRECISION,
  attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_population_welfare_lookup ON curated.population_welfare_features (area_level, district, sector);
CREATE INDEX IF NOT EXISTS idx_population_welfare_sector_lower ON curated.population_welfare_features (lower(sector)) WHERE area_level = 'sector';
CREATE INDEX IF NOT EXISTS idx_population_welfare_district_lower ON curated.population_welfare_features (lower(district)) WHERE area_level = 'district';

-- ==================== field: real-world observations (validation, not raw training labels) ====================

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

-- ==================== ml: training input, model registry, predictions ====================

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
  nearest_bus_station_m DOUBLE PRECISION,
  nearest_school_m DOUBLE PRECISION,
  nearest_health_m DOUBLE PRECISION,
  nearest_finance_m DOUBLE PRECISION,
  distance_to_main_road_m DOUBLE PRECISION,
  road_density_500m DOUBLE PRECISION DEFAULT 0,
  intersection_density_500m INTEGER DEFAULT 0,
  road_class_nearest TEXT,
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

-- ==================== app: product-facing tables (auth, saved data, preferences) ====================

CREATE TABLE IF NOT EXISTS app.users (
  id BIGSERIAL PRIMARY KEY,
  full_name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'entrepreneur',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

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
  label TEXT NOT NULL DEFAULT 'Saved location',
  business_category TEXT NOT NULL DEFAULT 'salon',
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

CREATE TABLE IF NOT EXISTS app.alerts (
  id BIGSERIAL PRIMARY KEY,
  saved_location_id BIGINT,
  alert_type TEXT NOT NULL DEFAULT 'opportunity',
  severity TEXT NOT NULL DEFAULT 'info',
  title TEXT NOT NULL,
  message TEXT,
  body TEXT,
  is_read BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.location_reports (
  id BIGSERIAL PRIMARY KEY,
  public_token TEXT,
  user_id BIGINT,
  saved_location_id BIGINT,
  title TEXT NOT NULL,
  business_category TEXT NOT NULL,
  latitude DOUBLE PRECISION,
  longitude DOUBLE PRECISION,
  report_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'ready',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_location_reports_public_token ON app.location_reports (public_token);
CREATE INDEX IF NOT EXISTS idx_location_reports_created_at ON app.location_reports (created_at);

CREATE TABLE IF NOT EXISTS app.notification_preferences (
  user_id BIGINT PRIMARY KEY,
  weekly_digest BOOLEAN NOT NULL DEFAULT TRUE,
  opportunity_alerts BOOLEAN NOT NULL DEFAULT TRUE,
  competition_alerts BOOLEAN NOT NULL DEFAULT TRUE,
  email_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.saved_workbench_states (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  business_category TEXT NOT NULL DEFAULT 'salon',
  center_lat DOUBLE PRECISION,
  center_lon DOUBLE PRECISION,
  zoom_level DOUBLE PRECISION NOT NULL DEFAULT 12,
  active_layers TEXT[] NOT NULL DEFAULT ARRAY['opportunity'],
  filters JSONB NOT NULL DEFAULT '{}'::jsonb,
  selected_locations JSONB NOT NULL DEFAULT '[]'::jsonb,
  state_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  is_pinned BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.user_preferences (
  user_id BIGINT PRIMARY KEY,
  default_business_category TEXT NOT NULL DEFAULT 'salon',
  default_radius_meters INTEGER NOT NULL DEFAULT 500,
  theme TEXT NOT NULL DEFAULT 'light',
  map_style TEXT NOT NULL DEFAULT 'standard',
  notification_frequency TEXT NOT NULL DEFAULT 'weekly',
  preferred_districts TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  preferred_budget_level TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.audit_log (
  id BIGSERIAL PRIMARY KEY,
  action TEXT NOT NULL,
  actor_user_id BIGINT,
  actor_role TEXT,
  entity_type TEXT,
  entity_id TEXT,
  request_id TEXT,
  ip_address INET,
  user_agent TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON app.audit_log (created_at DESC);

CREATE TABLE IF NOT EXISTS app.user_experience_events (
  id BIGSERIAL PRIMARY KEY,
  event_name TEXT NOT NULL,
  business_category TEXT,
  latitude DOUBLE PRECISION,
  longitude DOUBLE PRECISION,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  session_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE VIEW app.saved_location_summary AS
SELECT sl.*,
       p.opportunity_score AS latest_opportunity_score,
       p.risk_level AS latest_risk_level,
       p.confidence_score AS latest_confidence,
       COALESCE(a.unread_alerts, 0)::BIGINT AS unread_alerts
FROM app.saved_locations sl
LEFT JOIN LATERAL (
  SELECT opportunity_score, risk_level, confidence_score
  FROM ml.ml_opportunity_predictions p
  WHERE p.business_category = sl.business_category
  ORDER BY p.geom <-> ST_SetSRID(ST_MakePoint(sl.longitude, sl.latitude), 4326)
  LIMIT 1
) p ON TRUE
LEFT JOIN LATERAL (
  SELECT COUNT(*) AS unread_alerts
  FROM app.alerts a
  WHERE a.saved_location_id = sl.id AND a.is_read = FALSE
) a ON TRUE;

-- ==================== scoring helper functions ====================

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
  JOIN ml.model_versions mv ON mv.id = p.model_version_id
  WHERE p.business_category = p_category AND mv.is_active = TRUE
  ORDER BY p.geom <-> ST_SetSRID(ST_MakePoint(p_lon, p_lat), 4326)
  LIMIT 1;
END;
$$ LANGUAGE plpgsql STABLE;

-- ==================== seed data ====================

INSERT INTO curated.business_category_profiles (
  category_key, display_name, display_name_rw, description, description_rw, osm_filter,
  demand_weight, access_weight, commercial_weight, competition_weight, welfare_weight, min_confidence_threshold, is_active
) VALUES
('pharmacy','Pharmacy','Farumasi','Medicine access and health retail locations','Aho serivisi za farumasi n''imiti byoroshye kugerwaho','[{"key":"amenity","value":"pharmacy"},{"key":"healthcare","value":"pharmacy"}]',0.30,0.28,0.18,0.16,0.08,60,TRUE),
('restaurant','Restaurant and fast food','Resitora n''aho bagurisha ibiryo byihuse','Food service, restaurants and fast food businesses','Ubucuruzi bwa resitora n''ahagurishirizwa ibiryo byihuse','[{"key":"amenity","value":"restaurant"},{"key":"amenity","value":"fast_food"},{"key":"amenity","value":"food_court"}]',0.25,0.24,0.31,0.12,0.08,58,TRUE),
('cafe','Café','Kafe','Coffee, snack, study and social meeting places','Aho kunywera ikawa, gufata utuntu, kwiga cyangwa guhurira','[{"key":"amenity","value":"cafe"}]',0.22,0.22,0.34,0.14,0.08,55,TRUE),
('grocery','Supermarket and grocery','Supamaketi n''iduka ry''ibiribwa','Daily household goods, supermarkets and grocery stores','Amaduka y''ibiribwa n''ibikoresho byo mu rugo bya buri munsi','[{"key":"shop","value":"supermarket"},{"key":"shop","value":"grocery"},{"key":"shop","value":"convenience"},{"key":"shop","value":"greengrocer"}]',0.39,0.20,0.16,0.17,0.08,55,TRUE),
('salon','Salon and personal care','Saloon n''ubwiza','Hair, beauty, barbering and personal care services','Serivisi z''imisatsi, ubwiza, kogosha n''isuku y''umuntu','[{"key":"shop","value":"hairdresser"},{"key":"shop","value":"beauty"},{"key":"shop","value":"cosmetics"},{"key":"amenity","value":"barber"}]',0.34,0.20,0.22,0.16,0.08,45,TRUE)
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

-- Documents the real, currently-computed grid features for the
-- methodology/transparency pages. Kept in sync with build_grid_category_features.py.
INSERT INTO meta.feature_catalog
  (feature_name, feature_group, source_layer, geographic_level, business_category_specific, calculation_method, interpretation, quality_risk)
VALUES
  ('population_density_500m','Demand','curated.population_density_points','grid cell',false,'Average of WorldPop 1km density points within 500m of the cell centroid.','Fine-scale residential demand around the location.','1km source raster smooths local street-level variation.'),
  ('population_density_1000m','Demand','curated.population_density_points','grid cell',false,'Average of WorldPop 1km density points within 1000m of the cell centroid.','Wider catchment residential demand.','Same raster-resolution limitation as the 500m figure.'),
  ('sector_population','Demand','curated.population_count_features','sector',false,'Latest NISR population count for the cell''s sector.','Area-level market size.','Sector can be broader than the immediate walkable catchment.'),
  ('youth_share','Demand','curated.population_welfare_features (PHC5 2022)','sector, falls back to district',false,'Share of the sector''s census-weighted population aged 16-30.','Youth customer base context.','PHC5 is a 2022 snapshot; areas may have grown since.'),
  ('female_share','Demand','curated.population_welfare_features (PHC5 2022)','sector, falls back to district',false,'Share of the sector''s census-weighted population that is female.','Demographic context for category demand.','Aggregate share only - not a targeting signal.'),
  ('employment_rate','Purchasing power','curated.population_welfare_features (PHC5 2022 / LFS 2025)','sector, falls back to district',false,'Census/labour-force-survey employment-to-population ratio among working-age residents.','Local income-earning capacity.','PHC5''s employment question may undercount informal/subsistence work in rural sectors.'),
  ('income_proxy','Purchasing power','curated.population_welfare_features (PHC5 2022 / VUP 2025)','sector, falls back to district',false,'PHC5: housing-material durability + electricity + internet access, blended into a 0-100 index. District fallback: 100 minus the VUP-measured poverty rate.','Relative purchasing power of the surrounding area.','A housing/asset-based proxy where no sector-level income survey exists - not a direct income figure.'),
  ('welfare_proxy','Purchasing power','curated.population_welfare_features (PHC5 2022 / VUP 2025)','sector, falls back to district',false,'100 minus the poverty rate/proxy for the matching sector or district.','General household welfare level of the area.','District-level VUP poverty rate is a real measured rate; sector-level PHC5 figure is an asset-based proxy.'),
  ('establishment_category_count_area','Commercial environment','curated.establishment_area_features (NISR Establishment Census 2023)','district',true,'Count of census-registered establishments in the matching 1-digit ISIC division for the cell''s district.','Existing formal + informal business presence in this category.','District-level only (source has no sector/GPS field); pharmacy/grocery share one ISIC bucket, as do restaurant/cafe.'),
  ('nearest_bus_stop_m','Accessibility','curated.osm_poi_features','grid cell',false,'Minimum distance to a mapped transport stop.','Public-transport access.','OpenStreetMap transport-stop coverage is not guaranteed complete in every area.'),
  ('bus_stop_count_500m','Accessibility','curated.osm_poi_features','grid cell',false,'Count of mapped transport stops within 500m.','Density of public-transport access points.','Same OSM coverage caveat as nearest_bus_stop_m.'),
  ('market_distance_m','Commercial activity','curated.osm_poi_features','grid cell',false,'Distance to the nearest mapped market.','Proximity to a major demand generator.','Informal/unmapped markets are not captured.'),
  ('commercial_poi_count_500m','Commercial activity','curated.osm_poi_features','grid cell',false,'Count of commercial/food/finance/market points of interest within 500m.','General commercial intensity around the location.','Reflects OSM mapping completeness, not ground-truth footfall.'),
  ('competitor_count_300m','Competition','curated.osm_poi_features','grid cell + category',true,'Count of same-category OSM points within 300m.','Immediate competitive pressure.','Informal, unmapped competitors are not counted - a field-validation gap the app is upfront about.'),
  ('competitor_count_500m','Competition','curated.osm_poi_features','grid cell + category',true,'Count of same-category OSM points within 500m.','Neighbourhood-level competitive pressure.','Same OSM coverage caveat as the 300m figure.'),
  ('competitor_count_1000m','Competition','curated.osm_poi_features','grid cell + category',true,'Count of same-category OSM points within 1000m.','Wider-catchment competitive saturation.','Same OSM coverage caveat as the 300m figure.'),
  ('opportunity_gap_score','Opportunity index','ml.grid_category_features','grid cell + category',true,'Documented weighted composite of demand, accessibility, commercial activity, inverse competition, and welfare, refined by a trained model - not a business-success or revenue prediction.','Overall spatial suitability signal for the category.','Reflects data availability, not guaranteed outcomes - always paired with a confidence score and field-visit recommendations.')
ON CONFLICT (feature_name) DO UPDATE SET
  feature_group = EXCLUDED.feature_group,
  source_layer = EXCLUDED.source_layer,
  geographic_level = EXCLUDED.geographic_level,
  business_category_specific = EXCLUDED.business_category_specific,
  calculation_method = EXCLUDED.calculation_method,
  interpretation = EXCLUDED.interpretation,
  quality_risk = EXCLUDED.quality_risk;
"""
