CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.users (
    id BIGSERIAL PRIMARY KEY,
    email TEXT UNIQUE,
    full_name TEXT,
    role TEXT NOT NULL DEFAULT 'entrepreneur',
    organization_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS app.saved_locations (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES app.users(id) ON DELETE SET NULL,
    label TEXT NOT NULL,
    business_category TEXT NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    notes TEXT,
    latest_opportunity_score DOUBLE PRECISION,
    latest_risk_level TEXT,
    latest_confidence TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saved_locations_category ON app.saved_locations(business_category);
CREATE INDEX IF NOT EXISTS idx_saved_locations_point ON app.saved_locations USING GIST (ST_SetSRID(ST_MakePoint(longitude, latitude), 4326));

CREATE TABLE IF NOT EXISTS app.watchlists (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES app.users(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    business_category TEXT,
    district TEXT,
    alert_frequency TEXT NOT NULL DEFAULT 'weekly',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS app.alerts (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES app.users(id) ON DELETE SET NULL,
    saved_location_id BIGINT REFERENCES app.saved_locations(id) ON DELETE CASCADE,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS app.location_reports (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES app.users(id) ON DELETE SET NULL,
    saved_location_id BIGINT REFERENCES app.saved_locations(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    business_category TEXT NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    report_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'ready',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS app.location_comparisons (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES app.users(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    business_category TEXT NOT NULL,
    comparison_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
