"""Add village to geo.analysis_grid and thread it through ml.get_ml_prediction_near

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-10
"""
from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE geo.analysis_grid ADD COLUMN IF NOT EXISTS village TEXT;
        CREATE INDEX IF NOT EXISTS idx_analysis_grid_village ON geo.analysis_grid (village);

        UPDATE geo.analysis_grid g
        SET village = v.village
        FROM geo.admin_boundaries v
        WHERE v.boundary_level = 'village' AND v.geom IS NOT NULL
          AND ST_Contains(v.geom, g.centroid)
          AND g.village IS NULL;

        DROP FUNCTION IF EXISTS ml.get_ml_prediction_near(DOUBLE PRECISION, DOUBLE PRECISION, TEXT);
        CREATE FUNCTION ml.get_ml_prediction_near(p_lon DOUBLE PRECISION, p_lat DOUBLE PRECISION, p_category TEXT)
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
          cell TEXT,
          village TEXT
        ) AS $$
        BEGIN
          RETURN QUERY
          SELECT
            p.grid_id, p.business_category, p.opportunity_score, p.demand_score,
            p.accessibility_score, p.commercial_activity_score, p.competition_pressure,
            p.confidence_score, p.opportunity_rank, p.opportunity_type, p.zone_key,
            p.risk_level, p.explanation, p.model_version_id,
            ST_Distance(p.geom::geography, ST_SetSRID(ST_MakePoint(p_lon, p_lat), 4326)::geography) AS distance_m,
            p.geom, p.district, p.sector, p.cell, g.village
          FROM ml.ml_opportunity_predictions p
          JOIN ml.model_versions mv ON mv.id = p.model_version_id
          LEFT JOIN geo.analysis_grid g ON g.grid_id = p.grid_id
          WHERE p.business_category = p_category AND mv.is_active = TRUE
          ORDER BY p.geom <-> ST_SetSRID(ST_MakePoint(p_lon, p_lat), 4326)
          LIMIT 1;
        END;
        $$ LANGUAGE plpgsql STABLE;
    """)


def downgrade() -> None:
    op.execute("""
        DROP FUNCTION IF EXISTS ml.get_ml_prediction_near(DOUBLE PRECISION, DOUBLE PRECISION, TEXT);
        CREATE FUNCTION ml.get_ml_prediction_near(p_lon DOUBLE PRECISION, p_lat DOUBLE PRECISION, p_category TEXT)
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

        DROP INDEX IF EXISTS geo.idx_analysis_grid_village;
        ALTER TABLE geo.analysis_grid DROP COLUMN IF EXISTS village;
    """)
