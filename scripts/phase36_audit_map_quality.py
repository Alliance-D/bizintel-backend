"""Phase 36: audit BizIntel map cells for candidate-location quality.

Creates ml.map_quality_flags so the map can hide obvious non-candidate areas
such as water bodies and flag areas that need review because supporting signals
are very sparse.

Run from the project root after Phase 27/35 data exists:
  python scripts/phase36_audit_map_quality.py
"""
from __future__ import annotations

import os
import sys
from sqlalchemy import create_engine, text


def db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set. Activate the backend venv and set DATABASE_URL first.")
    return url


def has_column(conn, table_schema: str, table_name: str, column_name: str) -> bool:
    return bool(conn.execute(text("""
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = :schema AND table_name = :table AND column_name = :column
    """), {"schema": table_schema, "table": table_name, "column": column_name}).first())


def has_table(conn, table_schema: str, table_name: str) -> bool:
    return bool(conn.execute(text("""
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = :schema AND table_name = :table
    """), {"schema": table_schema, "table": table_name}).first())


def predicate(parts: list[str], default: str = "FALSE") -> str:
    return "(" + " OR ".join(parts) + ")" if parts else default


def main() -> int:
    engine = create_engine(db_url(), future=True)
    with engine.begin() as conn:
        if not has_table(conn, "geo", "analysis_grid"):
            raise SystemExit("geo.analysis_grid was not found. Run Phase 27 grid setup first.")
        if not has_table(conn, "curated", "osm_poi_features"):
            raise SystemExit("curated.osm_poi_features was not found. Run the OSM POI import first.")

        polygon_exists = has_table(conn, "public", "planet_osm_polygon")
        line_exists = has_table(conn, "public", "planet_osm_line")
        polygon_tags = polygon_exists and has_column(conn, "public", "planet_osm_polygon", "tags")
        line_tags = line_exists and has_column(conn, "public", "planet_osm_line", "tags")

        water_parts: list[str] = []
        building_parts: list[str] = []
        if polygon_exists:
            if has_column(conn, "public", "planet_osm_polygon", "natural"):
                water_parts.append("p.natural IN ('water','wetland','bay','strait')")
            if has_column(conn, "public", "planet_osm_polygon", "water"):
                water_parts.append("p.water IS NOT NULL")
            if has_column(conn, "public", "planet_osm_polygon", "waterway"):
                water_parts.append("p.waterway IS NOT NULL")
            if has_column(conn, "public", "planet_osm_polygon", "landuse"):
                water_parts.append("p.landuse IN ('reservoir','basin')")
            if has_column(conn, "public", "planet_osm_polygon", "leisure"):
                water_parts.append("p.leisure IN ('swimming_pool')")
            if polygon_tags:
                water_parts.extend([
                    "(p.tags -> 'natural') IN ('water','wetland','bay','strait')",
                    "(p.tags -> 'landuse') IN ('reservoir','basin')",
                    "(p.tags -> 'water') IS NOT NULL",
                    "(p.tags -> 'waterway') IS NOT NULL",
                ])
            if has_column(conn, "public", "planet_osm_polygon", "building"):
                building_parts.append("p.building IS NOT NULL AND p.building <> '' AND p.building <> 'no'")
            if polygon_tags:
                building_parts.append("(p.tags -> 'building') IS NOT NULL AND (p.tags -> 'building') <> 'no'")

        road_parts: list[str] = []
        if line_exists:
            if has_column(conn, "public", "planet_osm_line", "highway"):
                road_parts.append("l.highway IS NOT NULL AND l.highway <> ''")
            if line_tags:
                road_parts.append("(l.tags -> 'highway') IS NOT NULL")

        water_pred = predicate(water_parts)
        building_pred = predicate(building_parts)
        road_pred = predicate(road_parts)

        conn.execute(text("CREATE SCHEMA IF NOT EXISTS ml"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ml.map_quality_flags (
              grid_id TEXT PRIMARY KEY REFERENCES geo.analysis_grid(grid_id) ON DELETE CASCADE,
              water_overlap_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
              poi_count_500 INTEGER NOT NULL DEFAULT 0,
              building_count_300 INTEGER NOT NULL DEFAULT 0,
              road_count_300 INTEGER NOT NULL DEFAULT 0,
              candidate_status TEXT NOT NULL DEFAULT 'candidate',
              warning_labels JSONB NOT NULL DEFAULT '[]'::jsonb,
              notes TEXT,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        conn.execute(text("TRUNCATE ml.map_quality_flags"))

        water_cte = """
        water AS (
          SELECT g.grid_id,
                 COALESCE(
                   SUM(
                     ST_Area(
                       ST_Intersection(g.geom, ST_MakeValid(p.way))::geography
                     )
                   ) / NULLIF(ST_Area(g.geom::geography), 0),
                   0
                 ) AS water_ratio
          FROM geo.analysis_grid g
          LEFT JOIN public.planet_osm_polygon p
            ON {water_pred}
           AND ST_Intersects(g.geom, ST_MakeValid(p.way))
          GROUP BY g.grid_id
        ),
        """.format(water_pred=water_pred) if polygon_exists and water_parts else "water AS (SELECT grid_id, 0::double precision AS water_ratio FROM geo.analysis_grid),"

        building_cte = """
        buildings AS (
          SELECT g.grid_id, COUNT(p.*)::INTEGER AS building_count_300
          FROM geo.analysis_grid g
          LEFT JOIN public.planet_osm_polygon p
            ON {building_pred}
           AND ST_DWithin(g.centroid::geography, ST_PointOnSurface(ST_MakeValid(p.way))::geography, 300)
          GROUP BY g.grid_id
        ),
        """.format(building_pred=building_pred) if polygon_exists and building_parts else "buildings AS (SELECT grid_id, 0::integer AS building_count_300 FROM geo.analysis_grid),"

        road_cte = """
        roads AS (
          SELECT g.grid_id, COUNT(l.*)::INTEGER AS road_count_300
          FROM geo.analysis_grid g
          LEFT JOIN public.planet_osm_line l
            ON {road_pred}
           AND ST_DWithin(g.centroid::geography, l.way::geography, 300)
          GROUP BY g.grid_id
        ),
        """.format(road_pred=road_pred) if line_exists and road_parts else "roads AS (SELECT grid_id, 0::integer AS road_count_300 FROM geo.analysis_grid),"

        insert_sql = f"""
        WITH
        {water_cte}
        {building_cte}
        {road_cte}
        pois AS (
          SELECT g.grid_id, COUNT(o.*)::INTEGER AS poi_count_500
          FROM geo.analysis_grid g
          LEFT JOIN curated.osm_poi_features o
            ON ST_DWithin(g.centroid::geography, o.geom::geography, 500)
          GROUP BY g.grid_id
        ),
        combined AS (
          SELECT g.grid_id,
                 COALESCE(w.water_ratio, 0) AS water_ratio,
                 COALESCE(poi.poi_count_500, 0) AS poi_count_500,
                 COALESCE(b.building_count_300, 0) AS building_count_300,
                 COALESCE(r.road_count_300, 0) AS road_count_300
          FROM geo.analysis_grid g
          LEFT JOIN water w ON w.grid_id = g.grid_id
          LEFT JOIN pois poi ON poi.grid_id = g.grid_id
          LEFT JOIN buildings b ON b.grid_id = g.grid_id
          LEFT JOIN roads r ON r.grid_id = g.grid_id
        )
        INSERT INTO ml.map_quality_flags (
          grid_id, water_overlap_pct, poi_count_500, building_count_300, road_count_300,
          candidate_status, warning_labels, notes, updated_at
        )
        SELECT grid_id,
               ROUND((water_ratio * 100)::numeric, 2)::double precision AS water_overlap_pct,
               poi_count_500,
               building_count_300,
               road_count_300,
               CASE
                 WHEN water_ratio >= 0.35 THEN 'excluded_water'
                 WHEN poi_count_500 = 0 AND building_count_300 = 0 AND road_count_300 = 0 THEN 'review_low_signals'
                 ELSE 'candidate'
               END AS candidate_status,
               (
                 SELECT jsonb_agg(label)
                 FROM (
                   SELECT 'water_overlap' AS label WHERE water_ratio >= 0.20
                   UNION ALL SELECT 'no_nearby_pois' WHERE poi_count_500 = 0
                   UNION ALL SELECT 'no_nearby_buildings' WHERE building_count_300 = 0
                   UNION ALL SELECT 'no_nearby_roads' WHERE road_count_300 = 0
                 ) labels
               ) AS warning_labels,
               CASE
                 WHEN water_ratio >= 0.35 THEN 'Likely non-candidate area due to water overlap.'
                 WHEN poi_count_500 = 0 AND building_count_300 = 0 AND road_count_300 = 0 THEN 'Review before displaying as a candidate area; supporting signals are sparse.'
                 ELSE 'Candidate area passed the current quality screen.'
               END AS notes,
               now()
        FROM combined
        """
        conn.execute(text(insert_sql))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_map_quality_status ON ml.map_quality_flags(candidate_status)"))

        summary = conn.execute(text("""
            SELECT candidate_status, COUNT(*) AS count,
                   ROUND(AVG(water_overlap_pct)::numeric, 2) AS avg_water_overlap_pct,
                   ROUND(AVG(poi_count_500)::numeric, 2) AS avg_poi_count_500,
                   ROUND(AVG(building_count_300)::numeric, 2) AS avg_building_count_300,
                   ROUND(AVG(road_count_300)::numeric, 2) AS avg_road_count_300
            FROM ml.map_quality_flags
            GROUP BY candidate_status
            ORDER BY candidate_status
        """)).mappings().all()

        print("Phase 36 map quality audit complete")
        for row in summary:
            print(dict(row))

    return 0


if __name__ == "__main__":
    sys.exit(main())
