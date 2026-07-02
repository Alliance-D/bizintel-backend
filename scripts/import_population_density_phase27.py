"""Import population density CSV into curated.population_density_points.

Expected columns: X longitude, Y latitude, Z population density.
Example:
    python scripts/import_population_density_phase27.py data/raw/rwa_pd_2020_1km_ASCII_XYZ.csv --truncate
"""
from __future__ import annotations

import argparse
import os
import pandas as pd
from sqlalchemy import create_engine, text


def engine():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is required")
    return create_engine(url)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    parser.add_argument("--truncate", action="store_true")
    parser.add_argument("--chunksize", type=int, default=50000)
    args = parser.parse_args()
    eng = engine()
    total = 0
    with eng.begin() as conn:
        if args.truncate:
            conn.execute(text("TRUNCATE curated.population_density_points RESTART IDENTITY"))
    for chunk in pd.read_csv(args.csv_path, chunksize=args.chunksize):
        required = {"X", "Y", "Z"}
        missing = required.difference(chunk.columns)
        if missing:
            raise SystemExit(f"Missing required columns: {sorted(missing)}")
        rows = [
            {"x": float(row.X), "y": float(row.Y), "z": float(row.Z)}
            for row in chunk.itertuples(index=False)
            if pd.notna(row.X) and pd.notna(row.Y) and pd.notna(row.Z)
        ]
        if rows:
            with eng.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO curated.population_density_points (population_density, geom)
                        VALUES (:z, ST_SetSRID(ST_MakePoint(:x, :y), 4326))
                    """),
                    rows,
                )
        total += len(rows)
        print(f"Imported {total:,} population density points")
    print(f"Done. Imported {total:,} population density points")


if __name__ == "__main__":
    main()
