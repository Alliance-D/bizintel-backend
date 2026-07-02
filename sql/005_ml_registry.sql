-- Phase 3: ML registry, training run tracking, and prediction cache.
-- Run after 001-004.

CREATE SCHEMA IF NOT EXISTS ml;

CREATE TABLE IF NOT EXISTS ml.model_versions (
    id BIGSERIAL PRIMARY KEY,
    model_name TEXT NOT NULL,
    model_family TEXT NOT NULL,
    task_type TEXT NOT NULL CHECK (task_type IN ('classification', 'regression', 'count', 'ranking', 'segmentation')),
    business_scope TEXT NOT NULL DEFAULT 'multi_category',
    target_name TEXT NOT NULL,
    feature_set_name TEXT NOT NULL DEFAULT 'phase3_grid_category_features',
    artifact_uri TEXT NOT NULL,
    feature_schema_uri TEXT,
    metrics_uri TEXT,
    explanation_uri TEXT,
    training_data_uri TEXT,
    validation_strategy TEXT NOT NULL DEFAULT 'spatial_group_validation',
    primary_metric TEXT NOT NULL,
    primary_metric_value DOUBLE PRECISION,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    hyperparameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    feature_columns JSONB NOT NULL DEFAULT '[]'::jsonb,
    category_columns JSONB NOT NULL DEFAULT '[]'::jsonb,
    numeric_columns JSONB NOT NULL DEFAULT '[]'::jsonb,
    training_rows INTEGER,
    validation_rows INTEGER,
    model_notes TEXT,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    activated_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_model_versions_active ON ml.model_versions(is_active);
CREATE INDEX IF NOT EXISTS idx_model_versions_task ON ml.model_versions(task_type, target_name);

CREATE TABLE IF NOT EXISTS ml.training_runs (
    id BIGSERIAL PRIMARY KEY,
    run_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'created' CHECK (status IN ('created', 'running', 'completed', 'failed')),
    task_type TEXT NOT NULL,
    target_name TEXT NOT NULL,
    feature_set_name TEXT NOT NULL,
    input_uri TEXT,
    output_dir TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    best_model_version_id BIGINT REFERENCES ml.model_versions(id),
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ml.model_metrics (
    id BIGSERIAL PRIMARY KEY,
    model_version_id BIGINT NOT NULL REFERENCES ml.model_versions(id) ON DELETE CASCADE,
    split_name TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_model_metrics_version ON ml.model_metrics(model_version_id);

CREATE TABLE IF NOT EXISTS ml.feature_importance (
    id BIGSERIAL PRIMARY KEY,
    model_version_id BIGINT NOT NULL REFERENCES ml.model_versions(id) ON DELETE CASCADE,
    feature_name TEXT NOT NULL,
    importance_value DOUBLE PRECISION NOT NULL,
    rank INTEGER,
    source TEXT NOT NULL DEFAULT 'model_importance',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_feature_importance_version ON ml.feature_importance(model_version_id, rank);

CREATE TABLE IF NOT EXISTS ml.opportunity_predictions_cache (
    id BIGSERIAL PRIMARY KEY,
    grid_id BIGINT,
    business_category TEXT NOT NULL,
    model_version_id BIGINT REFERENCES ml.model_versions(id),
    opportunity_score DOUBLE PRECISION,
    presence_probability DOUBLE PRECISION,
    expected_business_count DOUBLE PRECISION,
    saturation_score DOUBLE PRECISION,
    opportunity_gap_score DOUBLE PRECISION,
    confidence_score DOUBLE PRECISION,
    opportunity_class TEXT,
    explanation JSONB NOT NULL DEFAULT '{}'::jsonb,
    geom geometry(Point, 4326),
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_opportunity_predictions_category ON ml.opportunity_predictions_cache(business_category);
CREATE INDEX IF NOT EXISTS idx_opportunity_predictions_grid ON ml.opportunity_predictions_cache(grid_id);
CREATE INDEX IF NOT EXISTS idx_opportunity_predictions_geom ON ml.opportunity_predictions_cache USING GIST(geom);

CREATE OR REPLACE VIEW ml.active_model_versions AS
SELECT *
FROM ml.model_versions
WHERE is_active = TRUE
ORDER BY activated_at DESC NULLS LAST, created_at DESC;
