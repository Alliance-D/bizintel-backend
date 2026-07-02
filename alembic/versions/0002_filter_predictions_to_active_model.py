"""Filter ml.get_ml_prediction_near to the active model version

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-02
"""
from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Without this, a location lookup could return a prediction from a
    # deactivated model version if it happened to be geometrically nearest.
    op.execute("""
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
    """)
    # Remove predictions left behind by model versions that are no longer active.
    op.execute("""
        DELETE FROM ml.ml_opportunity_predictions p
        USING ml.model_versions mv
        WHERE p.model_version_id = mv.id AND mv.is_active = FALSE;
    """)


def downgrade() -> None:
    op.execute("""
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
    """)
