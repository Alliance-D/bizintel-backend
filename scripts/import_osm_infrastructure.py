"""Normalize OSM roads and land-use into curated tables, and materialize a road
intersection layer used as a static footfall proxy.

Reads from the osm2pgsql tables (planet_osm_line for roads, planet_osm_polygon
for land use) that the .pbf is loaded into, and writes clean, SRID-4326,
GIST-indexed tables the feature builder queries:

  curated.osm_road_features       one row per mapped road (with class + flags)
  curated.osm_landuse             one row per land-use polygon
  curated.osm_road_intersections  points where street-network roads cross

Usage:
    python scripts/import_osm_infrastructure.py --truncate
"""
from __future__ import annotations

import argparse
import os

from sqlalchemy import create_engine, inspect, text

# Movement corridors: roads that carry vehicles/main pedestrian flow. Pure
# footpaths/tracks are excluded so the intersection self-join stays tractable and
# the proxy reflects the street network consistently (OSM footpath mapping in
# Kigali is patchy).
STREET_CLASSES = (
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "unclassified", "residential", "service", "living_street", "road", "pedestrian",
    "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link",
)
# "Main" roads for distance-to-main-road and visibility.
MAIN_CLASSES = (
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link",
)

DDL = """
CREATE TABLE IF NOT EXISTS curated.osm_road_features (
  id BIGSERIAL PRIMARY KEY,
  osm_id TEXT,
  highway TEXT,
  is_main BOOLEAN NOT NULL DEFAULT FALSE,
  is_street BOOLEAN NOT NULL DEFAULT FALSE,
  geom geometry(Geometry, 4326)
);
CREATE INDEX IF NOT EXISTS idx_osm_road_features_geom ON curated.osm_road_features USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_osm_road_features_main ON curated.osm_road_features (is_main) WHERE is_main;
-- Functional geography index: ST_DWithin(geom::geography, ...) casts the column,
-- so it needs an index on that exact expression, or every query seq-scans.
CREATE INDEX IF NOT EXISTS idx_osm_road_features_geog ON curated.osm_road_features USING GIST ((geom::geography)) WHERE is_street;

CREATE TABLE IF NOT EXISTS curated.osm_landuse (
  id BIGSERIAL PRIMARY KEY,
  osm_id TEXT,
  landuse TEXT,
  geom geometry(Geometry, 4326)
);
CREATE INDEX IF NOT EXISTS idx_osm_landuse_geom ON curated.osm_landuse USING GIST (geom);

CREATE TABLE IF NOT EXISTS curated.osm_road_intersections (
  id BIGSERIAL PRIMARY KEY,
  geom geometry(Point, 4326)
);
CREATE INDEX IF NOT EXISTS idx_osm_road_intersections_geom ON curated.osm_road_intersections USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_osm_road_intersections_geog ON curated.osm_road_intersections USING GIST ((geom::geography));
"""


def engine():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is required")
    return create_engine(url)


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def import_roads(conn) -> int:
    """Copy mapped roads from planet_osm_line into curated.osm_road_features."""
    sql = f"""
        INSERT INTO curated.osm_road_features (osm_id, highway, is_main, is_street, geom)
        SELECT osm_id::text, highway,
               highway IN ({_in_list(MAIN_CLASSES)}) AS is_main,
               highway IN ({_in_list(STREET_CLASSES)}) AS is_street,
               ST_MakeValid(way)
        FROM planet_osm_line
        WHERE highway IS NOT NULL AND way IS NOT NULL
    """
    return int(conn.execute(text(sql)).rowcount or 0)


def import_landuse(conn) -> int:
    """Copy land-use polygons from planet_osm_polygon into curated.osm_landuse."""
    sql = """
        INSERT INTO curated.osm_landuse (osm_id, landuse, geom)
        SELECT osm_id::text, landuse, ST_MakeValid(way)
        FROM planet_osm_polygon
        WHERE landuse IS NOT NULL AND way IS NOT NULL
    """
    return int(conn.execute(text(sql)).rowcount or 0)


def build_intersections(conn) -> int:
    """Materialize points where two street-network roads cross - a static proxy
    for how much movement a location sees (more intersections, more movement)."""
    sql = """
        INSERT INTO curated.osm_road_intersections (geom)
        SELECT DISTINCT geom FROM (
            SELECT (ST_Dump(ST_Intersection(a.geom, b.geom))).geom AS geom
            FROM curated.osm_road_features a
            JOIN curated.osm_road_features b
              ON a.id < b.id AND a.is_street AND b.is_street AND ST_Intersects(a.geom, b.geom)
        ) pts
        WHERE ST_GeometryType(geom) = 'ST_Point'
    """
    return int(conn.execute(text(sql)).rowcount or 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--truncate", action="store_true")
    args = parser.parse_args()
    eng = engine()

    if not inspect(eng).has_table("planet_osm_line"):
        raise SystemExit("planet_osm_line not found. Load the OSM extract with osm2pgsql first.")

    with eng.begin() as conn:
        conn.execute(text(DDL))
        if args.truncate:
            conn.execute(text("TRUNCATE curated.osm_road_features, curated.osm_landuse, curated.osm_road_intersections RESTART IDENTITY"))

    with eng.begin() as conn:
        roads = import_roads(conn)
        print(f"Imported {roads:,} roads")
    with eng.begin() as conn:
        landuse = import_landuse(conn)
        print(f"Imported {landuse:,} land-use polygons")
    with eng.begin() as conn:
        print("Building road intersection layer (this can take a couple of minutes)...")
        inter = build_intersections(conn)
        print(f"Built {inter:,} road intersections")
    print("Done.")


if __name__ == "__main__":
    main()
