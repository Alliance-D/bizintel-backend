CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS app.organizations (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  organization_type TEXT DEFAULT 'standard',
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.users (
  id BIGSERIAL PRIMARY KEY,
  organization_id BIGINT REFERENCES app.organizations(id) ON DELETE SET NULL,
  full_name TEXT NOT NULL,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'entrepreneur',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_app_users_email ON app.users(email);
CREATE INDEX IF NOT EXISTS idx_app_users_role ON app.users(role);

CREATE TABLE IF NOT EXISTS field.validation_points (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT REFERENCES app.users(id) ON DELETE SET NULL,
  business_category TEXT NOT NULL,
  latitude DOUBLE PRECISION NOT NULL,
  longitude DOUBLE PRECISION NOT NULL,
  geom geometry(Point, 4326) GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)) STORED,
  observed_activity TEXT,
  pedestrian_level TEXT,
  visible_competitors INTEGER,
  informal_competitors INTEGER,
  visibility_score INTEGER CHECK (visibility_score BETWEEN 1 AND 5),
  rent_signal TEXT,
  model_score NUMERIC(6,2),
  model_label TEXT,
  validator_notes TEXT,
  photo_url TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_validation_points_geom ON field.validation_points USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_validation_points_category ON field.validation_points(business_category);

CREATE TABLE IF NOT EXISTS app.notification_preferences (
  user_id BIGINT PRIMARY KEY REFERENCES app.users(id) ON DELETE CASCADE,
  weekly_digest BOOLEAN NOT NULL DEFAULT TRUE,
  opportunity_alerts BOOLEAN NOT NULL DEFAULT TRUE,
  competition_alerts BOOLEAN NOT NULL DEFAULT TRUE,
  email_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.report_exports (
  id BIGSERIAL PRIMARY KEY,
  report_id BIGINT REFERENCES app.location_reports(id) ON DELETE SET NULL,
  user_id BIGINT REFERENCES app.users(id) ON DELETE SET NULL,
  export_format TEXT NOT NULL DEFAULT 'pdf',
  file_url TEXT,
  status TEXT NOT NULL DEFAULT 'generated',
  created_at TIMESTAMPTZ DEFAULT now()
);
