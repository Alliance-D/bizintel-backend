"""Aggregate LFS 2025 and VUP welfare survey microdata into district-level
employment and poverty features.

These two national household surveys only carry district identifiers (no
sector), so they supplement - not replace - the sector-level PHC5 features
built by `import_population_welfare.py`. Grid feature generation prefers a
sector match from PHC5 and falls back to the district-level rows produced
here when a sector-level figure isn't available, and can also cross-check
the two sources against each other.

- LFS 2025 (`status1`, employment/unemployment/out-of-labour-force, survey
  weight `weight2`) gives a real employment-to-population ratio per district.
- VUP welfare (`pov_jan`, the official poverty-line indicator, survey weight
  `weight`) gives a real poverty rate per district - this is a directly
  measured poverty rate, not a proxy, so it takes priority over the PHC5
  housing-asset proxy where both exist.

Never loads the raw microdata into the application database - only the
aggregated district-level rows below.

Usage:
    python scripts/import_district_socioeconomic.py \
        --lfs "../other datasets/Microdata/RW_LFS2025.dta" \
        --vup "../other datasets/Microdata/vup_s8a1_expenditure.dta" \
        --truncate
"""
from __future__ import annotations

import argparse
import json
import os

import pyreadstat
from sqlalchemy import create_engine, text

WORKING_AGE_MIN = 16


def engine():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is required")
    return create_engine(url)


def aggregate_lfs_employment(path: str) -> dict[str, dict]:
    df, meta = pyreadstat.read_dta(path, encoding="latin1", usecols=["code_dis", "status1", "weight2", "A04"])
    district_labels = meta.variable_value_labels.get("code_dis", {})
    df["district"] = df["code_dis"].map(district_labels)
    df = df[df["A04"] >= WORKING_AGE_MIN].dropna(subset=["district"])

    results: dict[str, dict] = {}
    for district, group in df.groupby("district"):
        w = group["weight2"]
        working_age_w = float(w.sum())
        employed_w = float(w[group["status1"] == 1].sum())
        unemployed_w = float(w[group["status1"] == 2].sum())
        labour_force_w = employed_w + unemployed_w
        results[district] = {
            "employment_rate": (employed_w / working_age_w * 100) if working_age_w > 0 else None,
            "labour_force_participation_rate": (labour_force_w / working_age_w * 100) if working_age_w > 0 else None,
            "unemployment_rate": (unemployed_w / labour_force_w * 100) if labour_force_w > 0 else None,
            "lfs_sample_size": int(len(group)),
        }
    return results


def aggregate_vup_poverty(path: str) -> dict[str, dict]:
    df, meta = pyreadstat.read_dta(path, encoding="latin1", usecols=["district", "pov_jan", "epov_jan", "weight"])
    district_labels = meta.variable_value_labels.get("district", {})
    df["district_name"] = df["district"].map(district_labels)
    df = df.dropna(subset=["district_name"])

    # The .dta value labels for pov_jan/epov_jan claim a 0/100 scale, but the
    # underlying values are actually 0/1 flags - normalize against the
    # observed max so the result is a correct 0-100 rate regardless of which
    # coding the source file actually used.
    pov_scale = df["pov_jan"].max() or 1
    epov_scale = df["epov_jan"].max() or 1

    results: dict[str, dict] = {}
    for district, group in df.groupby("district_name"):
        w = group["weight"]
        total_w = float(w.sum())
        poverty_rate = float((group["pov_jan"] * w).sum() / total_w / pov_scale * 100) if total_w > 0 else None
        extreme_poverty_rate = float((group["epov_jan"] * w).sum() / total_w / epov_scale * 100) if total_w > 0 else None
        results[district] = {
            "poverty_proxy": poverty_rate,
            "extreme_poverty_rate": extreme_poverty_rate,
            "vup_sample_size": int(len(group)),
        }
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lfs", required=True, help="Path to RW_LFS2025.dta")
    parser.add_argument("--vup", required=True, help="Path to a VUP household/expenditure .dta with district + pov_jan")
    parser.add_argument("--truncate", action="store_true")
    args = parser.parse_args()

    lfs_by_district = aggregate_lfs_employment(args.lfs)
    vup_by_district = aggregate_vup_poverty(args.vup)
    districts = set(lfs_by_district) | set(vup_by_district)

    eng = engine()
    with eng.begin() as conn:
        if args.truncate:
            conn.execute(text("DELETE FROM curated.population_welfare_features WHERE source = 'lfs_vup_2025'"))

        for district in districts:
            lfs = lfs_by_district.get(district, {})
            vup = vup_by_district.get(district, {})
            attributes = json.dumps({
                "labour_force_participation_rate": lfs.get("labour_force_participation_rate"),
                "unemployment_rate": lfs.get("unemployment_rate"),
                "extreme_poverty_rate": vup.get("extreme_poverty_rate"),
                "lfs_sample_size": lfs.get("lfs_sample_size"),
                "vup_sample_size": vup.get("vup_sample_size"),
            })
            conn.execute(text("""
                INSERT INTO curated.population_welfare_features
                    (area_level, district, sector, source, employment_rate, poverty_proxy, income_proxy, attributes)
                VALUES
                    ('district', :district, NULL, 'lfs_vup_2025', :employment_rate, :poverty_proxy,
                     :income_proxy, CAST(:attributes AS jsonb))
            """), {
                "district": district,
                "employment_rate": lfs.get("employment_rate"),
                "poverty_proxy": vup.get("poverty_proxy"),
                # income_proxy as the inverse of the measured poverty rate, so it stays on the
                # same "higher is better" 0-100 scale as the PHC5 asset-based income_proxy.
                "income_proxy": (100 - vup["poverty_proxy"]) if vup.get("poverty_proxy") is not None else None,
                "attributes": attributes,
            })

        conn.execute(text("""
            INSERT INTO raw.dataset_imports
                (dataset_key, source_path, source_owner, license_status, rows_imported, import_status, finished_at)
            VALUES
                ('lfs_2025', :lfs_path, 'NISR', 'restricted_microdata_aggregated_only', :lfs_rows, 'complete', now())
        """), {"lfs_path": args.lfs, "lfs_rows": sum(v.get("lfs_sample_size", 0) for v in lfs_by_district.values())})
        conn.execute(text("""
            INSERT INTO raw.dataset_imports
                (dataset_key, source_path, source_owner, license_status, rows_imported, import_status, finished_at)
            VALUES
                ('vup_welfare_2025', :vup_path, 'NISR/LODA', 'restricted_microdata_aggregated_only', :vup_rows, 'complete', now())
        """), {"vup_path": args.vup, "vup_rows": sum(v.get("vup_sample_size", 0) for v in vup_by_district.values())})

    print(f"Aggregated LFS ({len(lfs_by_district)} districts) and VUP ({len(vup_by_district)} districts) into district-level feature rows")


if __name__ == "__main__":
    main()
