CREATE OR REPLACE FUNCTION ml.opportunity_tile(
  z integer,
  x integer,
  y integer,
  p_category text DEFAULT 'salon'
)
RETURNS bytea
LANGUAGE plpgsql
AS $$
DECLARE
  result bytea;
BEGIN
  WITH bounds AS (
    SELECT ST_TileEnvelope(z, x, y) AS geom
  ),
  mvtgeom AS (
    SELECT
      ST_AsMVTGeom(
        ST_Transform(COALESCE(g.geom, ST_SetSRID(ST_Point(g.longitude, g.latitude), 4326)), 3857),
        bounds.geom,
        4096,
        64,
        true
      ) AS geom,
      p.business_category,
      p.opportunity_score,
      p.demand_score,
      p.access_score,
      p.competition_pressure,
      p.confidence
    FROM ml.opportunity_prediction_cache p
    JOIN geo.analysis_grid g ON g.id = p.grid_id
    CROSS JOIN bounds
    WHERE p.business_category = p_category
      AND ST_Intersects(
        ST_Transform(COALESCE(g.geom, ST_SetSRID(ST_Point(g.longitude, g.latitude), 4326)), 3857),
        bounds.geom
      )
  )
  SELECT ST_AsMVT(mvtgeom, 'opportunity', 4096, 'geom') INTO result
  FROM mvtgeom;
  RETURN COALESCE(result, '\x'::bytea);
END;
$$;
