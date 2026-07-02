"""Normalize OSM businesses and POIs into curated.osm_poi_features.

This expects OSM to be loaded into PostGIS with osm2pgsql tables:
planet_osm_point and/or planet_osm_polygon.

Priority business categories:
pharmacy, restaurant including fast_food, cafe, grocery/supermarket, salon/personal care.
Support layers are also imported for access, demand generators and commercial activity.
"""
from __future__ import annotations

import argparse
import os
from sqlalchemy import create_engine, inspect, text

CATEGORY_TAGS = {
    "pharmacy": [("amenity", "pharmacy"), ("healthcare", "pharmacy")],
    "restaurant": [("amenity", "restaurant"), ("amenity", "fast_food"), ("amenity", "food_court")],
    "cafe": [("amenity", "cafe")],
    "grocery": [("shop", "supermarket"), ("shop", "grocery"), ("shop", "convenience"), ("shop", "greengrocer")],
    "salon": [("shop", "hairdresser"), ("shop", "beauty"), ("shop", "cosmetics"), ("amenity", "barber")],
    "transport": [("highway", "bus_stop"), ("amenity", "bus_station"), ("public_transport", "station")],
    "school": [("amenity", "school"), ("amenity", "university"), ("amenity", "college")],
    "health": [("amenity", "hospital"), ("amenity", "clinic"), ("healthcare", "clinic"), ("healthcare", "hospital")],
    "market": [("amenity", "marketplace")],
    "finance": [("amenity", "bank"), ("amenity", "atm")],
    "commercial_support": [("shop", "mall"), ("shop", "department_store"), ("shop", "clothes"), ("shop", "general")],
}

KEYS = ["name", "shop", "amenity", "healthcare", "tourism", "office", "highway", "public_transport", "landuse"]


def engine():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is required")
    return create_engine(url)


def exists(eng, table: str) -> bool:
    return inspect(eng).has_table(table)


def clauses(alias: str) -> str:
    parts = []
    for rules in CATEGORY_TAGS.values():
        for key, value in rules:
            parts.append(f'{alias}."{key}" = \'{value}\'')
    return " OR ".join(sorted(set(parts)))


def category_case(alias: str) -> str:
    parts = []
    for category, rules in CATEGORY_TAGS.items():
        cond = " OR ".join(f'{alias}."{k}" = \'{v}\'' for k, v in rules)
        parts.append(f"WHEN {cond} THEN '{category}'")
    return "CASE " + " ".join(parts) + " ELSE 'other' END"


def primary_key_case(alias: str) -> str:
    return "CASE " + " ".join(f'WHEN {alias}."{k}" IS NOT NULL THEN \'{k}\'' for k in KEYS[1:]) + " ELSE 'unknown' END"


def primary_value_case(alias: str) -> str:
    return "CASE " + " ".join(f'WHEN {alias}."{k}" IS NOT NULL THEN {alias}."{k}"' for k in KEYS[1:]) + " ELSE 'unknown' END"


def insert_from(eng, table: str, polygon: bool, limit: int | None) -> int:
    geom = "ST_PointOnSurface(ST_Transform(src.way, 4326))" if polygon else "ST_Transform(src.way, 4326)"
    tags = []
    for key in KEYS:
        tags.extend([f"'{key}'", f'src."{key}"'])
    limit_sql = "" if limit is None else f"LIMIT {int(limit)}"
    sql = f"""
    WITH inserted AS (
      INSERT INTO curated.osm_poi_features (osm_id, name, category_key, primary_key, primary_value, tags, source_layer, geom)
      SELECT src.osm_id::text, src.name, {category_case('src')}, {primary_key_case('src')}, {primary_value_case('src')},
             jsonb_strip_nulls(jsonb_build_object({', '.join(tags)})), '{table}', {geom}
      FROM {table} src
      WHERE src.way IS NOT NULL AND ({clauses('src')})
      {limit_sql}
      ON CONFLICT DO NOTHING
      RETURNING 1
    ) SELECT COUNT(*) FROM inserted
    """
    with eng.begin() as conn:
        return int(conn.execute(text(sql)).scalar() or 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--truncate", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    eng = engine()
    sources = []
    if exists(eng, "planet_osm_point"):
        sources.append(("planet_osm_point", False))
    if exists(eng, "planet_osm_polygon"):
        sources.append(("planet_osm_polygon", True))
    if not sources:
        raise SystemExit("No osm2pgsql tables found. Load your Rwanda/Kigali OSM extract first.")
    with eng.begin() as conn:
        if args.truncate:
            conn.execute(text("TRUNCATE curated.osm_poi_features RESTART IDENTITY"))
    total = 0
    for table, polygon in sources:
        count = insert_from(eng, table, polygon, args.limit)
        print(f"Imported {count:,} rows from {table}")
        total += count
    print(f"Done. Imported {total:,} OSM businesses and POIs")


if __name__ == "__main__":
    main()
