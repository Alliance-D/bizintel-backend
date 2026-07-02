"""Load generated dataset/variable catalogs into meta.dataset_catalog and meta.variable_catalog."""
from __future__ import annotations

import os
from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/bizintel")
CATALOG_DIR = Path(os.getenv("CATALOG_DIR", "docs/generated"))


def clean_value(v):
    if pd.isna(v):
        return None
    return v


def main() -> None:
    engine = create_engine(DATABASE_URL)
    dataset_path = CATALOG_DIR / "dataset_catalog.csv"
    variable_path = CATALOG_DIR / "variable_catalog.csv"
    if not dataset_path.exists():
        raise FileNotFoundError(f"Missing {dataset_path}; run inspect_datasets.py first")

    datasets = pd.read_csv(dataset_path)
    variables = pd.read_csv(variable_path) if variable_path.exists() else pd.DataFrame()

    with engine.begin() as conn:
        dataset_rows = []
        for _, r in datasets.iterrows():
            dataset_rows.append({
                "dataset_key": clean_value(r.get("dataset_key")),
                "title": clean_value(r.get("filename")) or clean_value(r.get("dataset_key")),
                "owner": clean_value(r.get("owner_likely")),
                "license_status": clean_value(r.get("license_status")) or "verify_before_use",
                "permission_status": clean_value(r.get("permission_status")) or "not_confirmed",
                "recommended_layer": clean_value(r.get("recommended_layer")),
                "relevance": clean_value(r.get("relevance")),
                "rows_estimate": clean_value(r.get("rows_estimate")),
                "columns_count": clean_value(r.get("columns_count")),
                "size_mb": clean_value(r.get("size_mb")),
                "raw_storage_path": clean_value(r.get("filename")),
                "notes": clean_value(r.get("inspection_note")),
            })
        conn.execute(text("""
            INSERT INTO meta.dataset_catalog (
                dataset_key, title, owner, license_status, permission_status,
                recommended_layer, relevance, rows_estimate, columns_count,
                size_mb, raw_storage_path, notes
            ) VALUES (
                :dataset_key, :title, :owner, :license_status, :permission_status,
                :recommended_layer, :relevance, :rows_estimate, :columns_count,
                :size_mb, :raw_storage_path, :notes
            )
            ON CONFLICT (dataset_key) DO UPDATE SET
                title = EXCLUDED.title,
                owner = EXCLUDED.owner,
                license_status = EXCLUDED.license_status,
                permission_status = EXCLUDED.permission_status,
                recommended_layer = EXCLUDED.recommended_layer,
                relevance = EXCLUDED.relevance,
                rows_estimate = EXCLUDED.rows_estimate,
                columns_count = EXCLUDED.columns_count,
                size_mb = EXCLUDED.size_mb,
                raw_storage_path = EXCLUDED.raw_storage_path,
                notes = EXCLUDED.notes
        """), dataset_rows)

        if not variables.empty:
            variable_rows = []
            for _, r in variables.iterrows():
                variable_rows.append({
                    "dataset_key": clean_value(r.get("dataset_key")),
                    "variable_name": clean_value(r.get("variable_name")),
                    "variable_label": clean_value(r.get("variable_label")),
                    "recommended_use": clean_value(r.get("recommended_use")) or "inspect",
                    "notes": clean_value(r.get("notes")),
                })
            # Batch inserts to avoid huge statements.
            stmt = text("""
                INSERT INTO meta.variable_catalog (dataset_key, variable_name, variable_label, recommended_use, notes)
                VALUES (:dataset_key, :variable_name, :variable_label, :recommended_use, :notes)
                ON CONFLICT (dataset_key, variable_name) DO UPDATE SET
                    variable_label = EXCLUDED.variable_label,
                    recommended_use = EXCLUDED.recommended_use,
                    notes = EXCLUDED.notes
            """)
            for start in range(0, len(variable_rows), 1000):
                conn.execute(stmt, variable_rows[start:start+1000])
    print(f"Imported {len(datasets):,} datasets and {len(variables):,} variables into metadata catalog")


if __name__ == "__main__":
    main()
