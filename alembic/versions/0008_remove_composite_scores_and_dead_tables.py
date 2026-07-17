"""Remove the retired composite scores and the dead saved-location/notification tables

The hand-weighted composite scores (demand/accessibility/commercial-activity/
welfare/competition-pressure/confidence and the old opportunity_gap_score target)
were display-only and are no longer produced or read anywhere - the model works
from raw fundamentals and outputs the gap percentile and a viability probability.
Drop those columns from both ML tables and recreate get_ml_prediction_near without
them. Also drop the saved-locations / alerts / notification-preferences tables and
their summary view: the features that used them (saved research, watchlist,
notifications) were removed from the product.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-17
"""
from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        -- 1. Dead saved-location / notification feature (view first, then tables).
        DROP VIEW IF EXISTS app.saved_location_summary;
        DROP TABLE IF EXISTS app.alerts CASCADE;
        DROP TABLE IF EXISTS app.notification_preferences CASCADE;
        DROP TABLE IF EXISTS app.saved_locations CASCADE;

        -- 2. Recreate the nearest-prediction function without composite columns
        --    (the return type changes, so it must be dropped and recreated).
        DROP FUNCTION IF EXISTS ml.get_ml_prediction_near(DOUBLE PRECISION, DOUBLE PRECISION, TEXT);
        CREATE FUNCTION ml.get_ml_prediction_near(p_lon DOUBLE PRECISION, p_lat DOUBLE PRECISION, p_category TEXT)
        RETURNS TABLE (
          grid_id TEXT,
          business_category TEXT,
          opportunity_score DOUBLE PRECISION,
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
            p.grid_id, p.business_category, p.opportunity_score,
            p.opportunity_rank, p.opportunity_type, p.zone_key,
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

        -- 3. Drop the composite columns from both ML tables.
        ALTER TABLE ml.grid_category_features
          DROP COLUMN IF EXISTS demand_score,
          DROP COLUMN IF EXISTS accessibility_score,
          DROP COLUMN IF EXISTS commercial_activity_score,
          DROP COLUMN IF EXISTS competition_pressure,
          DROP COLUMN IF EXISTS welfare_score,
          DROP COLUMN IF EXISTS opportunity_gap_score,
          DROP COLUMN IF EXISTS confidence_score;

        ALTER TABLE ml.ml_opportunity_predictions
          DROP COLUMN IF EXISTS demand_score,
          DROP COLUMN IF EXISTS accessibility_score,
          DROP COLUMN IF EXISTS commercial_activity_score,
          DROP COLUMN IF EXISTS competition_pressure,
          DROP COLUMN IF EXISTS confidence_score;

        -- 4. Retire the composite metadata and the old default target name.
        DELETE FROM meta.feature_catalog WHERE feature_name = 'opportunity_gap_score';
        ALTER TABLE ml.model_versions ALTER COLUMN target_name SET DEFAULT 'observed_count';
    """)


def downgrade() -> None:
    # The composite scores and the saved-location/notification feature are retired;
    # restoring them is out of scope. Re-add the columns as nullable so the schema
    # can round-trip, but they will be empty.
    op.execute("""
        ALTER TABLE ml.grid_category_features
          ADD COLUMN IF NOT EXISTS demand_score DOUBLE PRECISION DEFAULT 0,
          ADD COLUMN IF NOT EXISTS accessibility_score DOUBLE PRECISION DEFAULT 0,
          ADD COLUMN IF NOT EXISTS commercial_activity_score DOUBLE PRECISION DEFAULT 0,
          ADD COLUMN IF NOT EXISTS competition_pressure DOUBLE PRECISION DEFAULT 0,
          ADD COLUMN IF NOT EXISTS welfare_score DOUBLE PRECISION DEFAULT 0,
          ADD COLUMN IF NOT EXISTS opportunity_gap_score DOUBLE PRECISION DEFAULT 0,
          ADD COLUMN IF NOT EXISTS confidence_score DOUBLE PRECISION DEFAULT 0;
        ALTER TABLE ml.ml_opportunity_predictions
          ADD COLUMN IF NOT EXISTS demand_score DOUBLE PRECISION DEFAULT 0,
          ADD COLUMN IF NOT EXISTS accessibility_score DOUBLE PRECISION DEFAULT 0,
          ADD COLUMN IF NOT EXISTS commercial_activity_score DOUBLE PRECISION DEFAULT 0,
          ADD COLUMN IF NOT EXISTS competition_pressure DOUBLE PRECISION DEFAULT 0,
          ADD COLUMN IF NOT EXISTS confidence_score DOUBLE PRECISION DEFAULT 0;
        ALTER TABLE ml.model_versions ALTER COLUMN target_name SET DEFAULT 'opportunity_gap_score';
    """)
