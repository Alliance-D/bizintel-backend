CREATE EXTENSION IF NOT EXISTS postgis;

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS geo;
CREATE SCHEMA IF NOT EXISTS curated;
CREATE SCHEMA IF NOT EXISTS field;
CREATE SCHEMA IF NOT EXISTS ml;
CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS geo.analysis_grid (
    id BIGSERIAL PRIMARY KEY,
    grid_code TEXT UNIQUE,
    geom geometry(Polygon, 4326),
    centroid geometry(Point, 4326),
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_analysis_grid_geom ON geo.analysis_grid USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_analysis_grid_centroid ON geo.analysis_grid USING GIST (centroid);

CREATE TABLE IF NOT EXISTS geo.population_density_grid (
    id BIGSERIAL PRIMARY KEY,
    density DOUBLE PRECISION,
    geom geometry(Point, 4326)
);
CREATE INDEX IF NOT EXISTS idx_population_density_grid_geom ON geo.population_density_grid USING GIST (geom);

CREATE TABLE IF NOT EXISTS ml.training_features (
    id BIGSERIAL PRIMARY KEY,
    grid_id BIGINT,
    business_category TEXT NOT NULL,
    feature_payload JSONB NOT NULL,
    target_payload JSONB,
    generated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_training_features_category ON ml.training_features (business_category);

CREATE TABLE IF NOT EXISTS ml.model_versions (
    id BIGSERIAL PRIMARY KEY,
    model_name TEXT NOT NULL,
    version TEXT NOT NULL,
    business_category TEXT,
    artifact_uri TEXT NOT NULL,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(model_name, version)
);

CREATE TABLE IF NOT EXISTS ml.prediction_logs (
    id BIGSERIAL PRIMARY KEY,
    business_category TEXT NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    request_payload JSONB,
    response_payload JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.saved_locations (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT,
    name TEXT NOT NULL,
    business_category TEXT NOT NULL,
    geom geometry(Point, 4326),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_saved_locations_geom ON app.saved_locations USING GIST (geom);
