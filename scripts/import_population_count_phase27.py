"""Import sector population count CSV into curated.population_count_features.

Expected columns include district, sector, Male, Female, Total, period.
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
    args = parser.parse_args()
    df = pd.read_csv(args.csv_path)
    rows = []
    for row in df.itertuples(index=False):
        rows.append({
            "province": getattr(row, "province", None),
            "district": getattr(row, "district", None),
            "sector": getattr(row, "sector", None),
            "sector_id": str(getattr(row, "sector_id", "")),
            "male": int(getattr(row, "Male", 0) or 0),
            "female": int(getattr(row, "Female", 0) or 0),
            "total": int(getattr(row, "Total", 0) or 0),
            "period": int(getattr(row, "period", 0) or 0),
        })
    eng = engine()
    with eng.begin() as conn:
        if args.truncate:
            conn.execute(text("TRUNCATE curated.population_count_features RESTART IDENTITY"))
        if rows:
            conn.execute(
                text("""
                    INSERT INTO curated.population_count_features
                    (province, district, sector, sector_id, male, female, total_population, period)
                    VALUES (:province, :district, :sector, :sector_id, :male, :female, :total, :period)
                """),
                rows,
            )
    print(f"Done. Imported {len(rows):,} population count rows")


if __name__ == "__main__":
    main()
