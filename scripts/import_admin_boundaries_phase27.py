"""Import real administrative boundary geometries.

Supported inputs:
- GeoJSON or JSON with Polygon/MultiPolygon features
- CSV with a WKT geometry column such as geometry, geom, wkt, WKT

Examples:
    python scripts/import_admin_boundaries_phase27.py data/raw/kigali_districts.geojson --level district --truncate-level
    python scripts/import_admin_boundaries_phase27.py data/raw/kigali_sectors.csv --level sector --wkt-column geometry
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text


def engine():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is required")
    return create_engine(url)


def first_value(data: dict[str, Any], *keys: str) -> str | None:
    lower = {str(k).lower(): v for k, v in data.items()}
    for key in keys:
        value = lower.get(key.lower())
        if value not in (None, ""):
            return str(value)
    return None


def import_geojson(eng, path: Path, level: str) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    features = data.get("features", [])
    rows = []
    for feature in features:
        props = feature.get("properties") or {}
        geom = feature.get("geometry")
        if not geom:
            continue
        rows.append({
            "level": level,
            "province": first_value(props, "province", "prov_name"),
            "district": first_value(props, "district", "dist_name", "district_n"),
            "sector": first_value(props, "sector", "sect_name"),
            "cell": first_value(props, "cell", "cell_name"),
            "village": first_value(props, "village", "vill_name"),
            "source_id": first_value(props, "id", "fid", "objectid"),
            "attributes": json.dumps(props),
            "geometry": json.dumps(geom),
        })
    with eng.begin() as conn:
        if rows:
            conn.execute(text("""
                INSERT INTO geo.admin_boundaries
                (boundary_level, province, district, sector, cell, village, source_id, attributes, geom)
                VALUES (:level, :province, :district, :sector, :cell, :village, :source_id, CAST(:attributes AS jsonb), ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326)))
            """), rows)
    return len(rows)


def import_csv_wkt(eng, path: Path, level: str, wkt_column: str) -> int:
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or wkt_column not in reader.fieldnames:
            raise SystemExit(f"CSV must include WKT column {wkt_column!r}. Found {reader.fieldnames}")
        for props in reader:
            wkt = props.get(wkt_column)
            if not wkt:
                continue
            rows.append({
                "level": level,
                "province": first_value(props, "province", "prov_name"),
                "district": first_value(props, "district", "dist_name", "district_n"),
                "sector": first_value(props, "sector", "sect_name"),
                "cell": first_value(props, "cell", "cell_name"),
                "village": first_value(props, "village", "vill_name"),
                "source_id": first_value(props, "id", "fid", "objectid"),
                "attributes": json.dumps(props),
                "wkt": wkt,
            })
    with eng.begin() as conn:
        if rows:
            conn.execute(text("""
                INSERT INTO geo.admin_boundaries
                (boundary_level, province, district, sector, cell, village, source_id, attributes, geom)
                VALUES (:level, :province, :district, :sector, :cell, :village, :source_id, CAST(:attributes AS jsonb), ST_Multi(ST_SetSRID(ST_GeomFromText(:wkt), 4326)))
            """), rows)
    return len(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--level", required=True, choices=["district", "sector", "cell", "village"])
    parser.add_argument("--wkt-column", default="geometry")
    parser.add_argument("--truncate-level", action="store_true")
    args = parser.parse_args()
    path = Path(args.path)
    eng = engine()
    with eng.begin() as conn:
        if args.truncate_level:
            conn.execute(text("DELETE FROM geo.admin_boundaries WHERE boundary_level = :level"), {"level": args.level})
    if path.suffix.lower() in {".geojson", ".json"}:
        count = import_geojson(eng, path, args.level)
    elif path.suffix.lower() == ".csv":
        count = import_csv_wkt(eng, path, args.level, args.wkt_column)
    else:
        raise SystemExit("Unsupported boundary file type. Use GeoJSON, JSON or CSV with WKT")
    print(f"Imported {count:,} {args.level} boundary geometries")


if __name__ == "__main__":
    main()
