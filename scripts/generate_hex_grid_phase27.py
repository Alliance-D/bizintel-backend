"""Generate a PostGIS hex analysis grid for Kigali.

The script uses a Kigali fallback bounding box when real boundary geometries are not imported yet.
A 500m hex radius is recommended for the first ML pass. Use 250m later if performance is acceptable.

Example:
    python scripts/generate_hex_grid_phase27.py --radius-m 500 --truncate
"""
from __future__ import annotations

import argparse
import os
from sqlalchemy import create_engine, text


def engine():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is required")
    return create_engine(url)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--radius-m", type=int, default=500)
    parser.add_argument("--truncate", action="store_true")
    args = parser.parse_args()
    radius = int(args.radius_m)
    sql = text("""
WITH config AS (
  SELECT
    CAST(:radius AS double precision) AS r,
    sqrt(3.0) * CAST(:radius AS double precision) AS x_step,
    1.5 * CAST(:radius AS double precision) AS y_step
),
boundary AS (
  SELECT COALESCE(
    (
      SELECT ST_Union(geom)
      FROM geo.admin_boundaries
      WHERE geom IS NOT NULL
        AND (
          lower(province) LIKE '%kigali%'
          OR lower(district) LIKE '%gasabo%'
          OR lower(district) LIKE '%kicukiro%'
          OR lower(district) LIKE '%nyarugenge%'
        )
    ),
    ST_MakeEnvelope(29.94, -2.06, 30.24, -1.82, 4326)
  ) AS geom
),
b3857 AS (
  SELECT ST_Transform(geom, 3857) AS geom
  FROM boundary
),
ext AS (
  SELECT
    ST_XMin(geom) AS xmin,
    ST_YMin(geom) AS ymin,
    ST_XMax(geom) AS xmax,
    ST_YMax(geom) AS ymax
  FROM b3857
),
rows AS (
  SELECT
    row_number() OVER () - 1 AS row_idx,
    gs.y::double precision AS y
  FROM ext
  CROSS JOIN config
  CROSS JOIN LATERAL generate_series(
    (ymin - r)::numeric,
    (ymax + r)::numeric,
    y_step::numeric
  ) AS gs(y)
),
cols AS (
  SELECT
    row_number() OVER () - 1 AS col_idx,
    gs.x::double precision AS x
  FROM ext
  CROSS JOIN config
  CROSS JOIN LATERAL generate_series(
    (xmin - r)::numeric,
    (xmax + r)::numeric,
    x_step::numeric
  ) AS gs(x)
),
centers AS (
  SELECT
    row_idx,
    col_idx,
    x + CASE WHEN mod(row_idx, 2) = 1 THEN (SELECT x_step / 2 FROM config) ELSE 0 END AS cx,
    y AS cy,
    (SELECT r FROM config) AS r
  FROM rows
  CROSS JOIN cols
),
hexes AS (
  SELECT
    'KGL-H' || CAST(CAST(:radius AS integer) AS text) || '-' || row_idx::text || '-' || col_idx::text AS grid_id,
    ST_Transform(
      ST_SetSRID(
        ST_MakePolygon(
          ST_MakeLine(ARRAY[
            ST_MakePoint(cx + r * cos(0.0), cy + r * sin(0.0)),
            ST_MakePoint(cx + r * cos(pi()/3), cy + r * sin(pi()/3)),
            ST_MakePoint(cx + r * cos(2*pi()/3), cy + r * sin(2*pi()/3)),
            ST_MakePoint(cx + r * cos(pi()), cy + r * sin(pi())),
            ST_MakePoint(cx + r * cos(4*pi()/3), cy + r * sin(4*pi()/3)),
            ST_MakePoint(cx + r * cos(5*pi()/3), cy + r * sin(5*pi()/3)),
            ST_MakePoint(cx + r * cos(0.0), cy + r * sin(0.0))
          ])
        ),
        3857
      ),
      4326
    ) AS geom
  FROM centers
),
clipped AS (
  SELECT
    h.grid_id,
    h.geom,
    ST_Centroid(h.geom) AS centroid
  FROM hexes h
  CROSS JOIN boundary b
  WHERE ST_Intersects(h.geom, b.geom)
),
labelled AS (
  SELECT
    c.grid_id,
    c.geom,
    c.centroid,
    d.district,
    s.sector,
    ce.cell
  FROM clipped c
  LEFT JOIN LATERAL (
    SELECT district FROM geo.admin_boundaries b
    WHERE b.boundary_level = 'district' AND b.geom IS NOT NULL AND ST_Contains(b.geom, c.centroid)
    LIMIT 1
  ) d ON TRUE
  LEFT JOIN LATERAL (
    SELECT sector FROM geo.admin_boundaries b
    WHERE b.boundary_level = 'sector' AND b.geom IS NOT NULL AND ST_Contains(b.geom, c.centroid)
    LIMIT 1
  ) s ON TRUE
  LEFT JOIN LATERAL (
    SELECT cell FROM geo.admin_boundaries b
    WHERE b.boundary_level = 'cell' AND b.geom IS NOT NULL AND ST_Contains(b.geom, c.centroid)
    LIMIT 1
  ) ce ON TRUE
)
INSERT INTO geo.analysis_grid (grid_id, cell_radius_m, geom, centroid, district, sector, cell)
SELECT grid_id, CAST(:radius AS integer), geom, centroid, district, sector, cell
FROM labelled
WHERE district IN ('Gasabo', 'Kicukiro', 'Nyarugenge')
ON CONFLICT (grid_id) DO UPDATE SET
  cell_radius_m = EXCLUDED.cell_radius_m,
  geom = EXCLUDED.geom,
  centroid = EXCLUDED.centroid,
  district = EXCLUDED.district,
  sector = EXCLUDED.sector,
  cell = EXCLUDED.cell;
    """)
    eng = engine()
    with eng.begin() as conn:
        if args.truncate:
            conn.execute(text("TRUNCATE geo.analysis_grid CASCADE"))
        conn.execute(sql, {"radius": radius})
        count = conn.execute(text("SELECT COUNT(*) FROM geo.analysis_grid WHERE cell_radius_m = :radius"), {"radius": radius}).scalar()
    print(f"Generated {count:,} hex grid cells at {radius}m radius")


if __name__ == "__main__":
    main()
