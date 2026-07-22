"""Phase 6 live dataset integration script.

This script imports the uploaded real datasets into curated/PostGIS-ready tables.
It is intentionally defensive: each importer checks whether the expected columns
exist and skips gracefully when a file is missing or a schema is different.

Usage examples:
  python scripts/import_live_datasets.py --data-dir /path/to/uploads --database-url postgresql://...
  python scripts/import_live_datasets.py --data-dir /mnt/data --only population_density population_count movement boundaries
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

try:
    import pyreadstat  # type: ignore
except Exception:  # optional dependency for .dta metadata/selected extraction
    pyreadstat = None


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip().lower().replace(" ", "_").replace("-", "_") for c in out.columns]
    return out


def find_file(data_dir: Path, *patterns: str) -> Path | None:
    for pattern in patterns:
        matches = sorted(data_dir.glob(pattern))
        if matches:
            return matches[0]
    return None


def log_run(conn, dataset_key: str, source_file: Path, status: str, row_count: int = 0, notes: str | None = None) -> None:
    conn.execute(
        text(
            """
            INSERT INTO raw.dataset_ingestion_runs(dataset_key, source_file, status, row_count, notes, finished_at)
            VALUES (:dataset_key, :source_file, :status, :row_count, :notes, now())
            """
        ),
        {
            "dataset_key": dataset_key,
            "source_file": str(source_file),
            "status": status,
            "row_count": row_count,
            "notes": notes,
        },
    )


def import_population_density(conn, data_dir: Path) -> None:
    file = find_file(data_dir, "rwa_pd_2020_1km_ASCII_XYZ.csv", "*pd*XYZ*.csv", "*population*density*.csv")
    if not file:
        return
    df = normalize_columns(pd.read_csv(file))
    x_col = "x" if "x" in df.columns else df.columns[0]
    y_col = "y" if "y" in df.columns else df.columns[1]
    z_col = "z" if "z" in df.columns else df.columns[2]
    rows = [
        {"density": float(row[z_col]), "lon": float(row[x_col]), "lat": float(row[y_col]), "source_file": file.name}
        for _, row in df[[x_col, y_col, z_col]].dropna().iterrows()
    ]
    conn.execute(text("TRUNCATE geo.population_density_grid"))
    if rows:
        conn.execute(
            text(
                """
                INSERT INTO geo.population_density_grid(density, geom, source_file)
                VALUES (:density, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :source_file)
                """
            ),
            rows,
        )
    log_run(conn, "population_density_grid", file, "success", len(rows))


def import_population_count(conn, data_dir: Path) -> None:
    file = find_file(data_dir, "population_count_*.csv", "*population_count*.csv")
    if not file:
        return
    df = normalize_columns(pd.read_csv(file))
    def pick(*candidates: str) -> str | None:
        for c in candidates:
            if c in df.columns:
                return c
        return None
    province = pick("province", "prov_name")
    district = pick("district", "districts", "dist_name")
    sector = pick("sector", "sect_name")
    sector_id = pick("sector_id", "sect_id", "id")
    male = pick("male", "males")
    female = pick("female", "females")
    total = pick("total", "population", "value")
    period = pick("period", "date", "year")
    rows = []
    for _, r in df.iterrows():
        m = float(r[male]) if male and pd.notna(r.get(male)) else None
        f = float(r[female]) if female and pd.notna(r.get(female)) else None
        t = float(r[total]) if total and pd.notna(r.get(total)) else (m or 0) + (f or 0) if (m is not None or f is not None) else None
        rows.append({
            "province": str(r.get(province, "")) if province else None,
            "district": str(r.get(district, "")) if district else None,
            "sector": str(r.get(sector, "")) if sector else None,
            "sector_id": str(r.get(sector_id, "")) if sector_id else None,
            "period": int(r[period]) if period and pd.notna(r.get(period)) else None,
            "male_population": m,
            "female_population": f,
            "total_population": t,
            "female_share": (f / t) if f is not None and t else None,
            "male_share": (m / t) if m is not None and t else None,
            "source_file": file.name,
        })
    conn.execute(text("TRUNCATE curated.sector_population_features"))
    if rows:
        conn.execute(
            text(
                """
                INSERT INTO curated.sector_population_features(
                    province, district, sector, sector_id, period, male_population, female_population,
                    total_population, female_share, male_share, source_file
                ) VALUES (
                    :province, :district, :sector, :sector_id, :period, :male_population, :female_population,
                    :total_population, :female_share, :male_share, :source_file
                )
                """
            ),
            rows,
        )
    log_run(conn, "sector_population_features", file, "success", len(rows))


def import_boundaries(conn, data_dir: Path) -> None:
    patterns = {
        "province": "Province_Boundary*.csv",
        "district": "district_boundary*.csv",
        "sector": "sector_boundary*.csv",
        "cell": "cell_boundary*.csv",
        "village": "village_boundary*.csv",
    }
    conn.execute(text("DELETE FROM raw.boundary_attributes"))
    total = 0
    for level, pattern in patterns.items():
        file = find_file(data_dir, pattern)
        if not file:
            continue
        df = normalize_columns(pd.read_csv(file))
        rows = []
        for _, r in df.iterrows():
            as_dict = {k: (None if pd.isna(v) else v) for k, v in r.to_dict().items()}
            rows.append({
                "boundary_level": level,
                "province": as_dict.get("province") or as_dict.get("prov_name"),
                "district": as_dict.get("district") or as_dict.get("districts") or as_dict.get("dist_name"),
                "sector": as_dict.get("sector") or as_dict.get("sect_name"),
                "cell": as_dict.get("cell") or as_dict.get("cell_name"),
                "village": as_dict.get("village") or as_dict.get("vill_name"),
                "source_row": json.dumps(as_dict, default=str),
                "source_file": file.name,
            })
        if rows:
            conn.execute(
                text(
                    """
                    INSERT INTO raw.boundary_attributes(boundary_level, province, district, sector, cell, village, source_row, source_file)
                    VALUES (:boundary_level, :province, :district, :sector, :cell, :village, CAST(:source_row AS jsonb), :source_file)
                    """
                ),
                rows,
            )
        total += len(rows)
        log_run(conn, f"boundary_{level}_attributes", file, "success", len(rows), "Attribute CSV imported. Add polygon geometry when available.")
    if total:
        print(f"Imported {total} boundary attribute rows")


def import_movement(conn, data_dir: Path) -> None:
    file = find_file(data_dir, "movement-distribution*.csv", "*movement*.csv")
    if not file:
        return
    use_cols = None
    df = normalize_columns(pd.read_csv(file, usecols=use_cols))
    # Keep Rwanda rows only if country column exists.
    if "country" in df.columns:
        df = df[df["country"].astype(str).str.upper().isin(["RWA", "RWANDA"])]
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "country": str(r.get("country", "RWA")),
            "gadm_id": str(r.get("gadm_id", "")),
            "gadm_name": str(r.get("gadm_name", r.get("polygon_name", ""))),
            "polygon_level": str(r.get("polygon_level", "")),
            "distance_category": str(r.get("home_to_ping_distance_category", r.get("distance_category", ""))),
            "distance_fraction": float(r.get("distance_category_ping_fraction", r.get("fraction", 0))) if pd.notna(r.get("distance_category_ping_fraction", r.get("fraction", 0))) else None,
            "observation_date": str(r.get("ds", r.get("date", "")))[:10] or None,
            "source_file": file.name,
        })
    conn.execute(text("TRUNCATE curated.movement_features"))
    if rows:
        conn.execute(
            text(
                """
                INSERT INTO curated.movement_features(country, gadm_id, gadm_name, polygon_level, distance_category, distance_fraction, observation_date, source_file)
                VALUES (:country, :gadm_id, :gadm_name, :polygon_level, :distance_category, :distance_fraction, :observation_date, :source_file)
                """
            ),
            rows,
        )
    log_run(conn, "movement_features", file, "success", len(rows))


def inspect_dta_metadata(conn, data_dir: Path) -> None:
    if pyreadstat is None:
        print("pyreadstat not installed; skipping .dta metadata inspection")
        return
    for file in data_dir.glob("*.dta"):
        try:
            _, meta = pyreadstat.read_dta(str(file), metadataonly=True)
            notes = f"variables={len(meta.column_names)}; labels_available={bool(meta.column_labels)}"
            log_run(conn, f"dta_metadata:{file.name}", file, "metadata_only", 0, notes)
        except Exception as exc:
            log_run(conn, f"dta_metadata:{file.name}", file, "failed", 0, str(exc))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=os.getenv("BIZINTEL_DATA_DIR", "/mnt/data"))
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/bizintel"))
    parser.add_argument("--only", nargs="*", default=[])
    args = parser.parse_args()
    data_dir = Path(args.data_dir)
    engine = create_engine(args.database_url)
    selected = set(args.only)
    all_steps: list[tuple[str, callable]] = [
        ("population_density", import_population_density),
        ("population_count", import_population_count),
        ("boundaries", import_boundaries),
        ("movement", import_movement),
        ("dta_metadata", inspect_dta_metadata),
    ]
    with engine.begin() as conn:
        for name, fn in all_steps:
            if selected and name not in selected:
                continue
            print(f"Running importer: {name}")
            fn(conn, data_dir)
    print("Phase 6 dataset import complete.")


if __name__ == "__main__":
    main()
