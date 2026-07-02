-- Phase 9: Production hardening, RBAC, saved workbench states, audit and notification readiness.
CREATE SCHEMA IF NOT EXISTS app;
CREATE SCHEMA IF NOT EXISTS ml;

CREATE TABLE IF NOT EXISTS app.user_sessions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL,
    device_label TEXT,
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON app.user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_expires_at ON app.user_sessions(expires_at);

CREATE TABLE IF NOT EXISTS app.user_preferences (
    user_id BIGINT PRIMARY KEY REFERENCES app.users(id) ON DELETE CASCADE,
    default_business_category TEXT NOT NULL DEFAULT 'salon',
    default_radius_meters INTEGER NOT NULL DEFAULT 500,
    theme TEXT NOT NULL DEFAULT 'dark',
    map_style TEXT NOT NULL DEFAULT 'dark',
    notification_frequency TEXT NOT NULL DEFAULT 'weekly',
    preferred_districts TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    preferred_budget_level TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.saved_workbench_states (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    business_category TEXT NOT NULL,
    center_lat DOUBLE PRECISION,
    center_lon DOUBLE PRECISION,
    zoom_level DOUBLE PRECISION DEFAULT 12,
    active_layers TEXT[] NOT NULL DEFAULT ARRAY['opportunity']::TEXT[],
    filters JSONB NOT NULL DEFAULT '{}'::JSONB,
    selected_locations JSONB NOT NULL DEFAULT '[]'::JSONB,
    state_payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    is_pinned BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_saved_workbench_user ON app.saved_workbench_states(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_saved_workbench_category ON app.saved_workbench_states(business_category);

CREATE TABLE IF NOT EXISTS app.audit_log (
    id BIGSERIAL PRIMARY KEY,
    actor_user_id BIGINT REFERENCES app.users(id) ON DELETE SET NULL,
    actor_role TEXT,
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    ip_address INET,
    user_agent TEXT,
    request_id TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_log_actor ON app.audit_log(actor_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON app.audit_log(action, created_at DESC);

CREATE TABLE IF NOT EXISTS app.report_exports (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES app.users(id) ON DELETE SET NULL,
    report_type TEXT NOT NULL DEFAULT 'location_assessment',
    title TEXT NOT NULL,
    business_category TEXT NOT NULL,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    file_path TEXT,
    status TEXT NOT NULL DEFAULT 'generated',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.api_usage_events (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES app.users(id) ON DELETE SET NULL,
    route TEXT NOT NULL,
    method TEXT NOT NULL,
    status_code INTEGER,
    latency_ms INTEGER,
    ip_address INET,
    user_agent TEXT,
    request_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_api_usage_route_time ON app.api_usage_events(route, created_at DESC);

CREATE OR REPLACE FUNCTION app.touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_saved_workbench_touch ON app.saved_workbench_states;
CREATE TRIGGER trg_saved_workbench_touch
BEFORE UPDATE ON app.saved_workbench_states
FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();

DROP TRIGGER IF EXISTS trg_user_preferences_touch ON app.user_preferences;
CREATE TRIGGER trg_user_preferences_touch
BEFORE UPDATE ON app.user_preferences
FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
