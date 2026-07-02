"""Build curated OSM business/POI feature layer from osm2pgsql tables.

This script expects an OSM extract already loaded into PostGIS by osm2pgsql.
It reads planet_osm_point and planet_osm_polygon, normalizes relevant tags into
curated.osm_poi_features, and maps POIs to platform business categories.

Example:
    DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/bizintel \
    python scripts/import_osm_business_features.py --truncate
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import create_engine, inspect, text

CATEGORY_TAGS = {
    "salon": [("shop", "hairdresser"), ("shop", "beauty"), ("shop", "cosmetics")],
    "pharmacy": [("amenity", "pharmacy"), ("healthcare", "pharmacy")],
    "cafe": [("amenity", "cafe"), ("amenity", "restaurant"), ("amenity", "fast_food")],
    "grocery": [("shop", "convenience"), ("shop", "supermarket"), ("shop", "grocery")],
    "retail": [("shop", "mall"), ("shop", "clothes"), ("shop", "general"), ("shop", "department_store")],
    "market": [("amenity", "marketplace")],
    "school": [("amenity", "school"), ("amenity", "university"), ("amenity", "college")],
    "health": [("amenity", "hospital"), ("amenity", "clinic"), ("healthcare", "clinic"), ("healthcare", "hospital")],
    "transport": [("highway", "bus_stop"), ("amenity", "bus_station"), ("public_transport", "station")],
    "finance": [("amenity", "bank"), ("amenity", "atm"), ("office", "financial")],
    "hotel": [("tourism", "hotel"), ("tourism", "guest_house")],
}

ALL_KEYS = sorted({k for rules in CATEGORY_TAGS.values() for k, _ in rules} | {"name", "osm_id"})


def get_engine():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is required.")
    return create_engine(database_url)


def table_exists(engine, name: str) -> bool:
    schema = None
    table = name
    if "." in name:
        schema, table = name.split(".", 1)
    return inspect(engine).has_table(table, schema=schema)


def source_tables(engine) -> list[tuple[str, str]]:
    candidates = []
    if table_exists(engine, "planet_osm_point"):
        candidates.append(("planet_osm_point", "point"))
    if table_exists(engine, "planet_osm_polygon"):
        candidates.append(("planet_osm_polygon", "polygon"))
    if not candidates:
        raise RuntimeError("No osm2pgsql tables found. Expected planet_osm_point and/or planet_osm_polygon.")
    return candidates


def create_filter_sql(alias: str = "src") -> str:
    clauses = []
    for rules in CATEGORY_TAGS.values():
        for key, value in rules:
            if value == "*":
                clauses.append(f"{alias}.\"{key}\" IS NOT NULL")
            else:
                clauses.append(f"{alias}.\"{key}\" = '{value}'")
    return " OR ".join(sorted(set(clauses)))


def category_case(alias: str = "src") -> str:
    parts = []
    for category, rules in CATEGORY_TAGS.items():
        conds = []
        for key, value in rules:
            if value == "*":
                conds.append(f"{alias}.\"{key}\" IS NOT NULL")
            else:
                conds.append(f"{alias}.\"{key}\" = '{value}'")
        parts.append(f"WHEN {' OR '.join(conds)} THEN '{category}'")
    return "CASE " + " ".join(parts) + " ELSE 'other' END"


def primary_key_case(alias: str = "src") -> str:
    cases = []
    for key in ["shop", "amenity", "healthcare", "tourism", "office", "highway", "public_transport", "landuse"]:
        cases.append(f"WHEN {alias}.\"{key}\" IS NOT NULL THEN '{key}'")
    return "CASE " + " ".join(cases) + " ELSE 'unknown' END"


def primary_value_case(alias: str = "src") -> str:
    cases = []
    for key in ["shop", "amenity", "healthcare", "tourism", "office", "highway", "public_transport", "landuse"]:
        cases.append(f"WHEN {alias}.\"{key}\" IS NOT NULL THEN {alias}.\"{key}\"")
    return "CASE " + " ".join(cases) + " ELSE 'unknown' END"


def insert_from_source(engine, table: str, layer_type: str, limit: int | None = None) -> int:
    where = create_filter_sql("src")
    limit_clause = "" if limit is None else f"LIMIT {int(limit)}"
    geom_expr = "ST_Transform(src.way, 4326)" if layer_type == "point" else "ST_PointOnSurface(ST_Transform(src.way, 4326))"

    tag_pairs = []
    for key in ["name", "shop", "amenity", "healthcare", "tourism", "office", "highway", "public_transport", "landuse"]:
        tag_pairs.extend([f"'{key}'", f"src.\"{key}\""])
    tags_expr = "jsonb_strip_nulls(jsonb_build_object(" + ", ".join(tag_pairs) + "))"

    sql = f"""
        WITH inserted AS (
            INSERT INTO curated.osm_poi_features (
                osm_id, name, category_key, primary_key, primary_value, tags, source_layer, geom
            )
            SELECT
                src.osm_id::text AS osm_id,
                src.name,
                {category_case('src')} AS category_key,
                {primary_key_case('src')} AS primary_key,
                {primary_value_case('src')} AS primary_value,
                {tags_expr} AS tags,
                '{table}' AS source_layer,
                {geom_expr} AS geom
            FROM {table} src
            WHERE ({where})
              AND src.way IS NOT NULL
            {limit_clause}
            RETURNING 1
        )
        SELECT COUNT(*) FROM inserted;
    """
    with engine.begin() as conn:
        return int(conn.execute(text(sql)).scalar() or 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--truncate", action="store_true", help="Clear curated.osm_poi_features before import.")
    parser.add_argument("--limit", type=int, default=None, help="Optional per-source-table row limit for testing.")
    args = parser.parse_args()

    engine = get_engine()
    with engine.begin() as conn:
        if args.truncate:
            conn.execute(text("TRUNCATE curated.osm_poi_features RESTART IDENTITY"))

    total = 0
    for table, layer_type in source_tables(engine):
        count = insert_from_source(engine, table, layer_type, args.limit)
        total += count
        print(f"Imported {count:,} rows from {table}.")
    print(f"Done. Total OSM POI/business features imported: {total:,}")


if __name__ == "__main__":
    main()
