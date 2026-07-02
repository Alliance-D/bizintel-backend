"""Aggregate PHC5 (2022 Population and Housing Census) microdata into
sector-level demographic and welfare features.

PHC5 carries province/district/sector codes (ml01/ml02/ml03) - the same
resolution as the analysis grid's sector attribute, unlike the establishment
census or LFS/VUP which only go down to district. Person-level rows are
aggregated using the census sampling weight (Pop_weight) so results are
population-representative, not just raw counts.

The census has no direct income question, so `income_proxy` here is a
housing/asset-based welfare proxy (roof/wall/floor material durability +
electricity + internet access), not a survey income figure. This is a
standard substitute used in multidimensional poverty measurement (e.g. DHS
wealth index methodology) - documented rather than hidden, and it is the
same underlying number as `asset_welfare_index`.

Never loads the raw microdata into the application database - only the
aggregated sector-level rows below.

Usage:
    python scripts/import_population_welfare.py "../other datasets/PHC5_Public_microdata.dta" --truncate
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np
import pandas as pd
import pyreadstat
from sqlalchemy import create_engine, text

YOUTH_AGE_RANGE = (16, 30)  # matches the 16-30 youth definition used throughout this project
WORKING_AGE_RANGE = (16, 64)

DURABLE_ROOF = {1, 3, 5}          # Iron sheets, industrial tiles, concrete
DURABLE_WALL = {6, 7, 8, 11}       # Cement blocks, concrete, stones with cement, burnt bricks with cement
DURABLE_FLOOR = {3, 4, 5, 6, 7, 8}  # Concrete, stones, burnt bricks, wooden floor, ceramic/tiles, cement

PHC5_COLUMNS = ["ml02", "ml03", "p03", "p04", "p49", "h14", "p34", "h05", "h06", "h07", "Pop_weight"]


def engine():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is required")
    return create_engine(url)


def weighted_share(mask: pd.Series, weight: pd.Series, denom_weight: float) -> float:
    if denom_weight <= 0:
        return 0.0
    return float((weight[mask]).sum() / denom_weight * 100)


def aggregate_sector(group: pd.DataFrame) -> dict:
    w = group["Pop_weight"]
    total_w = float(w.sum())
    age = group["p04"]
    working_age_mask = age.between(*WORKING_AGE_RANGE)
    working_age_w = float(w[working_age_mask].sum())
    employed_mask = working_age_mask & group["p49"].notna()

    housing_durability = np.mean([
        weighted_share(group["h05"].isin(DURABLE_ROOF), w, total_w),
        weighted_share(group["h06"].isin(DURABLE_WALL), w, total_w),
        weighted_share(group["h07"].isin(DURABLE_FLOOR), w, total_w),
    ]) if total_w > 0 else 0.0
    electricity_share = weighted_share(group["h14"] == 1, w, total_w)
    internet_share = weighted_share(group["p34"] == 1, w, total_w)
    asset_welfare_index = 0.5 * housing_durability + 0.25 * electricity_share + 0.25 * internet_share

    return {
        "population_sample_size": int(len(group)),
        "youth_share": weighted_share(age.between(*YOUTH_AGE_RANGE), w, total_w),
        "female_share": weighted_share(group["p03"] == 2, w, total_w),
        "working_age_share": weighted_share(working_age_mask, w, total_w),
        "employment_rate": weighted_share(employed_mask, w, working_age_w) if working_age_w > 0 else 0.0,
        "electricity_access_share": electricity_share,
        "internet_access_share": internet_share,
        "asset_welfare_index": asset_welfare_index,
        "poverty_proxy": max(0.0, 100.0 - asset_welfare_index),
        "income_proxy": asset_welfare_index,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source_path", help="Path to the PHC5_Public_microdata.dta file")
    parser.add_argument("--truncate", action="store_true")
    args = parser.parse_args()

    df, meta = pyreadstat.read_dta(args.source_path, encoding="latin1", usecols=PHC5_COLUMNS)
    district_labels = meta.variable_value_labels.get("ml02", {})
    sector_labels = meta.variable_value_labels.get("ml03", {})
    df["district"] = df["ml02"].map(district_labels)
    df["sector"] = df["ml03"].map(sector_labels)
    df = df.dropna(subset=["district", "sector"])

    rows = []
    for (district, sector), group in df.groupby(["district", "sector"]):
        stats = aggregate_sector(group)
        rows.append({
            "area_level": "sector",
            "district": district,
            "sector": sector,
            "source": "phc5_2022",
            **stats,
        })

    eng = engine()
    with eng.begin() as conn:
        if args.truncate:
            conn.execute(text("DELETE FROM curated.population_welfare_features WHERE source = 'phc5_2022'"))
        for row in rows:
            row = dict(row)
            row["attributes"] = json.dumps({"unweighted_sample_size": row["population_sample_size"]})
            conn.execute(text("""
                INSERT INTO curated.population_welfare_features
                    (area_level, district, sector, source, population_sample_size,
                     youth_share, female_share, working_age_share, employment_rate,
                     electricity_access_share, internet_access_share,
                     asset_welfare_index, poverty_proxy, income_proxy, attributes)
                VALUES
                    (:area_level, :district, :sector, :source, :population_sample_size,
                     :youth_share, :female_share, :working_age_share, :employment_rate,
                     :electricity_access_share, :internet_access_share,
                     :asset_welfare_index, :poverty_proxy, :income_proxy, CAST(:attributes AS jsonb))
            """), row)
        conn.execute(text("""
            INSERT INTO raw.dataset_imports
                (dataset_key, source_path, source_owner, license_status, rows_imported, import_status, finished_at)
            VALUES
                ('phc5_census_2022', :source_path, 'NISR', 'restricted_microdata_aggregated_only', :rows, 'complete', now())
        """), {"source_path": args.source_path, "rows": len(df)})

    print(f"Aggregated {len(df):,} PHC5 person records into {len(rows):,} sector-level welfare feature rows")


if __name__ == "__main__":
    main()
