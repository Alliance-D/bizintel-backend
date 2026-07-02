-- Phase 8: Product experience, interactive insight, and map UX support.
-- This layer does not replace ML predictions. It turns ML output into product-ready
-- narratives, badges, and fast map/detail responses.

CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.user_experience_events (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NULL,
    session_id TEXT NULL,
    event_name TEXT NOT NULL,
    business_category TEXT NULL,
    latitude DOUBLE PRECISION NULL,
    longitude DOUBLE PRECISION NULL,
    payload JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_experience_events_name_time
    ON app.user_experience_events (event_name, created_at DESC);

CREATE TABLE IF NOT EXISTS app.product_tours (
    tour_key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    steps JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_active BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMPTZ DEFAULT now()
);

INSERT INTO app.product_tours (tour_key, title, description, steps)
VALUES
('opportunity_workbench', 'Explore Kigali opportunity intelligence', 'Guides users through category selection, map layers, scout mode, competitive advantage, and saved locations.',
 '[
   {"title":"Choose a business category","body":"Switch the ML opportunity surface between salons, pharmacies, cafes, restaurants, groceries, and retail."},
   {"title":"Read the map like a market analyst","body":"Use demand, access, competition, confidence, and opportunity layers to understand what is happening in an area."},
   {"title":"Click a cell for a scout report","body":"The system summarizes opportunity score, demand, competition pressure, confidence, and practical next steps."},
   {"title":"Compare and save","body":"Save promising locations, compare them, and return later to monitor risk or opportunity changes."}
 ]'::jsonb)
ON CONFLICT (tour_key) DO UPDATE
SET title = EXCLUDED.title,
    description = EXCLUDED.description,
    steps = EXCLUDED.steps,
    updated_at = now();

CREATE OR REPLACE VIEW ml.v_opportunity_experience_cells AS
SELECT
    p.id,
    p.grid_id,
    p.business_category,
    p.opportunity_score,
    p.demand_score,
    p.accessibility_score,
    p.commercial_activity_score,
    p.competition_pressure,
    p.confidence_score,
    p.opportunity_rank,
    p.opportunity_type,
    p.model_version_id,
    p.explanation,
    ST_Y(p.geom) AS latitude,
    ST_X(p.geom) AS longitude,
    CASE
        WHEN p.opportunity_score >= 82 AND p.confidence_score >= 60 THEN 'Prime Opportunity'
        WHEN p.opportunity_score >= 70 THEN 'Strong Candidate'
        WHEN p.competition_pressure >= 75 AND p.demand_score >= 65 THEN 'High Demand / Crowded'
        WHEN p.demand_score >= 65 AND COALESCE(p.competition_pressure, 0) < 45 THEN 'Underserved Pocket'
        WHEN p.confidence_score < 45 THEN 'Needs Validation'
        ELSE 'Watch Zone'
    END AS experience_badge,
    CASE
        WHEN p.opportunity_score >= 82 AND p.confidence_score >= 60 THEN 'Prioritize physical verification, rent check, and competitor walk-through.'
        WHEN p.opportunity_score >= 70 THEN 'Compare with nearby alternatives and check frontage/rent quality.'
        WHEN p.competition_pressure >= 75 AND p.demand_score >= 65 THEN 'Opportunity may exist only with differentiation, premium service, or niche targeting.'
        WHEN p.demand_score >= 65 AND COALESCE(p.competition_pressure, 0) < 45 THEN 'Potential underserved area; validate informal competition and customer flow.'
        WHEN p.confidence_score < 45 THEN 'Treat as exploratory until field validation improves confidence.'
        ELSE 'Monitor this area and compare with stronger opportunity cells.'
    END AS recommended_next_step
FROM ml.ml_opportunity_predictions p;
