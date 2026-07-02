from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine
from app.db.data_layer_sql import PHASE27_DATA_LAYER_SQL


BOOTSTRAP_SQL = """
CREATE SCHEMA IF NOT EXISTS app;
CREATE SCHEMA IF NOT EXISTS field;
CREATE SCHEMA IF NOT EXISTS meta;
CREATE SCHEMA IF NOT EXISTS geo;
CREATE SCHEMA IF NOT EXISTS curated;
CREATE SCHEMA IF NOT EXISTS ml;

CREATE TABLE IF NOT EXISTS app.users (
  id BIGSERIAL PRIMARY KEY,
  full_name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'entrepreneur',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

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

CREATE TABLE IF NOT EXISTS app.saved_locations (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT,
  label TEXT NOT NULL,
  business_category TEXT NOT NULL DEFAULT 'salon',
  latitude DOUBLE PRECISION NOT NULL,
  longitude DOUBLE PRECISION NOT NULL,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.location_reports (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT,
  saved_location_id BIGINT,
  title TEXT NOT NULL,
  business_category TEXT NOT NULL,
  latitude DOUBLE PRECISION NOT NULL,
  longitude DOUBLE PRECISION NOT NULL,
  report_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'ready',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

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
  user_id BIGINT,
  user_email TEXT,
  user_role TEXT,
  entity_type TEXT,
  entity_id TEXT,
  request_id TEXT,
  ip_address TEXT,
  user_agent TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

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

CREATE TABLE IF NOT EXISTS field.validation_points (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT,
  business_category TEXT NOT NULL,
  latitude DOUBLE PRECISION NOT NULL,
  longitude DOUBLE PRECISION NOT NULL,
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

CREATE TABLE IF NOT EXISTS meta.dataset_catalog (
  id BIGSERIAL PRIMARY KEY,
  dataset_key TEXT UNIQUE,
  title TEXT,
  owner TEXT,
  license_status TEXT,
  permission_status TEXT,
  recommended_layer TEXT,
  relevance TEXT,
  rows_estimate BIGINT,
  columns_count INTEGER,
  size_mb DOUBLE PRECISION,
  imported_at TIMESTAMPTZ DEFAULT now(),
  notes TEXT
);

CREATE TABLE IF NOT EXISTS meta.feature_catalog (
  id BIGSERIAL PRIMARY KEY,
  feature_name TEXT UNIQUE,
  feature_group TEXT,
  source_layer TEXT,
  geographic_level TEXT,
  business_category_specific BOOLEAN DEFAULT FALSE,
  used_for_training BOOLEAN DEFAULT TRUE,
  used_for_prediction BOOLEAN DEFAULT TRUE,
  calculation_method TEXT,
  interpretation TEXT,
  quality_risk TEXT
);

-- Compatibility for databases created by earlier phases. Some had `name`,
-- later phases use `label`. Keep both so saves work without resetting data.
ALTER TABLE app.saved_locations ADD COLUMN IF NOT EXISTS label TEXT;
ALTER TABLE app.saved_locations ADD COLUMN IF NOT EXISTS name TEXT DEFAULT 'Saved location';
ALTER TABLE app.saved_locations ADD COLUMN IF NOT EXISTS geom geometry(Point, 4326);
ALTER TABLE app.saved_locations ADD COLUMN IF NOT EXISTS opportunity_score DOUBLE PRECISION;
ALTER TABLE app.saved_locations ADD COLUMN IF NOT EXISTS risk_level TEXT;
UPDATE app.saved_locations
SET label = COALESCE(label, name, 'Saved location'),
    name = COALESCE(name, label, 'Saved location'),
    geom = COALESCE(geom, ST_SetSRID(ST_MakePoint(longitude, latitude), 4326))
WHERE label IS NULL OR name IS NULL OR geom IS NULL;
ALTER TABLE app.saved_locations ALTER COLUMN label SET DEFAULT 'Saved location';
ALTER TABLE app.saved_locations ALTER COLUMN name SET DEFAULT 'Saved location';
CREATE INDEX IF NOT EXISTS idx_saved_locations_geom ON app.saved_locations USING GIST (geom);

DROP VIEW IF EXISTS app.saved_location_summary;

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
"""


def bootstrap_database(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        conn.execute(text(BOOTSTRAP_SQL))
        conn.execute(text(PHASE27_DATA_LAYER_SQL))
