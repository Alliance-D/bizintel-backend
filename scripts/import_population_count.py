"""Import sector-level population count and generate curated sector features.

Expected flexible columns include province, district, sector, sector_id, Male, Female,
Total, period/Date/year. The script keeps only aggregated features needed by the app.
"""
from __future__ import annotations

import os
import pandas as pd
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/bizintel")
CSV_PATH = os.getenv("POP_COUNT_CSV", "data/raw/population_count_6456351076777895603.csv")


def norm(s: str) -> str:
    return s.strip().lower().replace(" ", "_").replace("-", "_")


def main() -> None:
    engine = create_engine(DATABASE_URL)
    df = pd.read_csv(CSV_PATH)
    df.columns = [norm(c) for c in df.columns]

    sector_col = "sector" if "sector" in df.columns else "sector_name"
    district_col = "district" if "district" in df.columns else "district_name"
    sector_id_col = "sector_id" if "sector_id" in df.columns else sector_col
    year_col = "period" if "period" in df.columns else "date" if "date" in df.columns else "year"
    total_col = "total" if "total" in df.columns else "value"
    male_col = "male" if "male" in df.columns else None
    female_col = "female" if "female" in df.columns else None

    df[year_col] = df[year_col].astype(str).str.extract(r"(\d{4})").astype(float).astype("Int64")
    pivot = df.pivot_table(index=[sector_id_col, sector_col, district_col], columns=year_col, values=total_col, aggfunc="sum").reset_index()
    latest_year = max([c for c in pivot.columns if isinstance(c, (int, float)) or str(c).isdigit()])
    latest_year = int(latest_year)
    prev_year = 2012 if 2012 in pivot.columns else None

    latest = df[df[year_col] == latest_year].copy()
    latest_group = latest.groupby([sector_id_col, sector_col, district_col], dropna=False).agg(
        population_latest=(total_col, "sum"),
        male_latest=(male_col, "sum") if male_col else (total_col, "size"),
        female_latest=(female_col, "sum") if female_col else (total_col, "size"),
    ).reset_index()

    merged = latest_group.merge(pivot, on=[sector_id_col, sector_col, district_col], how="left")
    if prev_year and prev_year in merged.columns:
        merged["growth_2012_latest"] = (merged[latest_year] - merged[prev_year]) / merged[prev_year].replace({0: pd.NA})
    else:
        merged["growth_2012_latest"] = pd.NA
    merged["female_share"] = merged["female_latest"] / merged["population_latest"].replace({0: pd.NA})
    merged["male_share"] = merged["male_latest"] / merged["population_latest"].replace({0: pd.NA})

    rows = []
    for _, r in merged.iterrows():
        rows.append({
            "sector_id": str(r[sector_id_col]),
            "sector_name": str(r[sector_col]),
            "district_name": str(r[district_col]),
            "population_2022": int(r["population_latest"]) if pd.notna(r["population_latest"]) else None,
            "population_2012": int(r[prev_year]) if prev_year and prev_year in merged.columns and pd.notna(r[prev_year]) else None,
            "population_growth_2012_2022": float(r["growth_2012_latest"]) if pd.notna(r["growth_2012_latest"]) else None,
            "female_share_2022": float(r["female_share"]) if pd.notna(r["female_share"]) else None,
            "male_share_2022": float(r["male_share"]) if pd.notna(r["male_share"]) else None,
            "source_dataset": os.path.basename(CSV_PATH),
        })

    upsert = text("""
        INSERT INTO curated.sector_population_features (
            sector_id, sector_name, district_name, population_2022, population_2012,
            population_growth_2012_2022, female_share_2022, male_share_2022, source_dataset
        ) VALUES (
            :sector_id, :sector_name, :district_name, :population_2022, :population_2012,
            :population_growth_2012_2022, :female_share_2022, :male_share_2022, :source_dataset
        )
        ON CONFLICT (sector_id) DO UPDATE SET
            sector_name = EXCLUDED.sector_name,
            district_name = EXCLUDED.district_name,
            population_2022 = EXCLUDED.population_2022,
            population_2012 = EXCLUDED.population_2012,
            population_growth_2012_2022 = EXCLUDED.population_growth_2012_2022,
            female_share_2022 = EXCLUDED.female_share_2022,
            male_share_2022 = EXCLUDED.male_share_2022,
            source_dataset = EXCLUDED.source_dataset,
            updated_at = now()
    """)

    with engine.begin() as conn:
        conn.execute(upsert, rows)
    print(f"Imported {len(rows):,} curated sector population feature rows")


if __name__ == "__main__":
    main()
