-- Phase 10: demo seed data and final release/readiness views.

CREATE SCHEMA IF NOT EXISTS app;
CREATE SCHEMA IF NOT EXISTS ml;
CREATE SCHEMA IF NOT EXISTS curated;

CREATE TABLE IF NOT EXISTS app.release_checklist (
    id SERIAL PRIMARY KEY,
    area TEXT NOT NULL,
    item TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    notes TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.demo_scenarios (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    persona TEXT NOT NULL,
    business_category TEXT NOT NULL,
    location_label TEXT NOT NULL,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    objective TEXT NOT NULL,
    expected_story TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO app.release_checklist (area, item, status, notes)
VALUES
('Data', 'Dataset catalog generated and reviewed', 'pending', 'Run dataset inspection and import catalog scripts'),
('Data', 'Restricted dataset permissions documented', 'pending', 'Do not publish restricted raw datasets'),
('Spatial', 'PostGIS extension enabled', 'pending', 'Required for spatial joins and distance calculations'),
('Spatial', 'Analysis grid generated for Kigali', 'pending', 'Used by opportunity map and category scoring'),
('ML', 'Training matrix generated', 'pending', 'One row = grid cell + business category'),
('ML', 'Multiple candidate models compared', 'pending', 'Keep metrics and active model metadata'),
('ML', 'Active model registered', 'pending', 'Required before true ML-backed predictions'),
('Product', 'Scout Mode demo works', 'pending', 'Pin/location assessment flow'),
('Product', 'Opportunity Map demo works', 'pending', 'Category-specific opportunity layer'),
('Product', 'Competitive Advantage demo works', 'pending', 'Competitor/catchment story'),
('Security', 'Environment variables configured', 'pending', 'No secrets in repository'),
('Deployment', 'Smoke tests pass', 'pending', 'Run scripts/route_smoke_test.py')
ON CONFLICT DO NOTHING;

INSERT INTO app.demo_scenarios (title, persona, business_category, location_label, latitude, longitude, objective, expected_story)
VALUES
('Salon scouting near dense residential demand', 'First-time entrepreneur', 'salon', 'Kimironko residential-commercial edge', -1.9366, 30.1304, 'Assess whether the area supports a differentiated personal care service.', 'High demand and access should be weighed against competition pressure.'),
('Pharmacy opportunity near health and residential anchors', 'Microfinance advisor', 'pharmacy', 'Kacyiru mixed-use corridor', -1.9456, 30.0878, 'Compare health-adjacent opportunity and road access.', 'Useful when demand generators and accessibility are strong but supply is moderate.'),
('Cafe opportunity around offices and schools', 'Existing business owner', 'cafe', 'Remera commercial strip', -1.9536, 30.1044, 'Find a category fit for daytime commercial activity.', 'Commercial POIs and walkability should drive the recommendation.'),
('Grocery underserved pocket scan', 'Youth entrepreneur', 'grocery', 'Residential pocket in Kicukiro', -1.9790, 30.1020, 'Discover if daily-needs retail is underserved.', 'High residential density and low direct supply should create an opportunity gap.')
ON CONFLICT DO NOTHING;

CREATE OR REPLACE VIEW app.v_release_readiness AS
SELECT
    area,
    COUNT(*) AS total_items,
    COUNT(*) FILTER (WHERE status = 'done') AS done_items,
    COUNT(*) FILTER (WHERE status <> 'done') AS open_items,
    ROUND((COUNT(*) FILTER (WHERE status = 'done')::numeric / NULLIF(COUNT(*), 0)) * 100, 1) AS completion_pct
FROM app.release_checklist
GROUP BY area
ORDER BY area;

CREATE OR REPLACE VIEW app.v_demo_scenarios AS
SELECT
    id,
    title,
    persona,
    business_category,
    location_label,
    latitude,
    longitude,
    objective,
    expected_story,
    created_at
FROM app.demo_scenarios
ORDER BY id;
