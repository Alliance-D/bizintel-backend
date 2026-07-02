DROP VIEW IF EXISTS app.saved_location_summary;

CREATE OR REPLACE VIEW app.saved_location_summary AS
SELECT
    sl.id,
    sl.label,
    sl.business_category,
    sl.latitude,
    sl.longitude,
    sl.latest_opportunity_score,
    sl.latest_risk_level,
    sl.latest_confidence,
    sl.created_at,
    COUNT(a.id) FILTER (WHERE a.is_read = FALSE) AS unread_alerts
FROM app.saved_locations sl
LEFT JOIN app.alerts a ON a.saved_location_id = sl.id
GROUP BY sl.id;
