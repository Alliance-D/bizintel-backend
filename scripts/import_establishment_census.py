"""Aggregate the NISR Establishment Census into district-level business features.

The source microdata (data-rwa-nisr-ec-2023v2.dta) only carries province and
district identifiers (no sector/cell), and its economic-activity variable
(q6_1, ISIC major division) is a single digit — coarse enough that some of
our five active product categories share the same ISIC bucket:

    restaurant, cafe   -> ISIC 9  (Accommodation and Food Service Activities)
    pharmacy, grocery  -> ISIC 7  (Wholesale and Retail Trade)
    salon              -> ISIC 19 (Other Service Activities, incl. personal care)

Where two categories share a bucket, they intentionally get the same
establishment-density signal for that district rather than a fabricated,
falsely-precise split. This is a real limitation of the source data, not a
bug - it is called out again in the ML notebook.

Never loads the raw microdata into the application database - only the
aggregated counts below, at district level.

Usage:
    python scripts/import_establishment_census.py "../other datasets/data-rwa-nisr-ec-2023v2.dta" --truncate
"""
from __future__ import annotations

import argparse
import json
import os
import re

import pandas as pd
import pyreadstat
from sqlalchemy import create_engine, text

# ISIC major-division code -> product category keys it contributes to.
ISIC_TO_CATEGORIES = {
    7: ["pharmacy", "grocery"],
    9: ["restaurant", "cafe"],
    19: ["salon"],
}

# Rough turnover-bracket midpoints in RWF, used only to rank/compare areas,
# not to make an exact revenue claim.
TURNOVER_BRACKET_MIDPOINT_RWF = {
    1: 150_000,
    2: 6_150_000,
    3: 16_000_000,
    4: 35_000_000,
    5: 225_000_000,
    6: 700_000_000,
    7: 1_500_000_000,
}


def engine():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is required")
    return create_engine(url)


def clean_district_name(label: str) -> str:
    """'12 -Gasabo' / '21- Nyanza' -> 'Gasabo' / 'Nyanza'."""
    name = re.split(r"-", label, maxsplit=1)[-1]
    return name.strip()


def load_establishments(path: str) -> pd.DataFrame:
    df, meta = pyreadstat.read_dta(
        path,
        encoding="latin1",
        usecols=["q1_2", "q6_1", "FI", "Total_workers", "q20"],
    )
    district_labels = meta.variable_value_labels.get("q1_2", {})
    df["district"] = df["q1_2"].map(lambda code: clean_district_name(district_labels.get(code, str(code))))
    df["turnover_rwf"] = df["q20"].map(TURNOVER_BRACKET_MIDPOINT_RWF)
    return df


def aggregate_by_district_category(df: pd.DataFrame) -> list[dict]:
    rows: list[dict] = []
    for district, district_df in df.groupby("district"):
        # Per-category rows for the ISIC buckets that map to a product category.
        for isic_code, categories in ISIC_TO_CATEGORIES.items():
            bucket = district_df[district_df["q6_1"] == isic_code]
            if bucket.empty:
                continue
            formal = int((bucket["FI"] == 1).sum())
            informal = int((bucket["FI"] == 2).sum())
            worker_count = int(bucket["Total_workers"].sum())
            turnover_proxy = float(bucket["turnover_rwf"].mean()) if bucket["turnover_rwf"].notna().any() else None
            for category in categories:
                rows.append({
                    "area_level": "district",
                    "district": district,
                    "sector": None,
                    "cell": None,
                    "business_category": category,
                    "establishment_count": int(len(bucket)),
                    "worker_count": worker_count,
                    "formal_count": formal,
                    "informal_count": informal,
                    "turnover_proxy": turnover_proxy,
                    "isic_major_division": isic_code,
                })
        # Overall district row across all economic activities, for a general
        # commercial-activity signal independent of any one category.
        formal_all = int((district_df["FI"] == 1).sum())
        informal_all = int((district_df["FI"] == 2).sum())
        rows.append({
            "area_level": "district",
            "district": district,
            "sector": None,
            "cell": None,
            "business_category": "all",
            "establishment_count": int(len(district_df)),
            "worker_count": int(district_df["Total_workers"].sum()),
            "formal_count": formal_all,
            "informal_count": informal_all,
            "turnover_proxy": float(district_df["turnover_rwf"].mean()) if district_df["turnover_rwf"].notna().any() else None,
            "isic_major_division": None,
        })
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source_path", help="Path to the establishment census .dta file")
    parser.add_argument("--truncate", action="store_true")
    args = parser.parse_args()

    df = load_establishments(args.source_path)
    rows = aggregate_by_district_category(df)

    eng = engine()
    with eng.begin() as conn:
        if args.truncate:
            conn.execute(text("DELETE FROM curated.establishment_area_features"))
        for raw_row in rows:
            row = {k: v for k, v in raw_row.items() if k != "isic_major_division"}
            row["attributes"] = json.dumps({"isic_major_division": raw_row["isic_major_division"]})
            conn.execute(text("""
                INSERT INTO curated.establishment_area_features
                    (area_level, district, sector, cell, business_category,
                     establishment_count, worker_count, formal_count, informal_count,
                     turnover_proxy, attributes)
                VALUES
                    (:area_level, :district, :sector, :cell, :business_category,
                     :establishment_count, :worker_count, :formal_count, :informal_count,
                     :turnover_proxy, CAST(:attributes AS jsonb))
            """), row)
        conn.execute(text("""
            INSERT INTO raw.dataset_imports
                (dataset_key, source_path, source_owner, license_status, rows_imported, import_status, finished_at)
            VALUES
                ('establishment_census_2023', :source_path, 'NISR', 'restricted_microdata_aggregated_only', :rows, 'complete', now())
        """), {"source_path": args.source_path, "rows": len(df)})

    print(f"Aggregated {len(df):,} establishment records into {len(rows):,} district-level feature rows")


if __name__ == "__main__":
    main()
