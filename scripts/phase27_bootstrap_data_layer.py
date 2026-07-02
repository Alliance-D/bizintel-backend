"""Bootstrap the Phase 27 PostGIS data layer.

Run from the project root after DATABASE_URL is set:
    python scripts/phase27_bootstrap_data_layer.py
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.db.data_layer_sql import PHASE27_DATA_LAYER_SQL


def main() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required")
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        conn.execute(text(PHASE27_DATA_LAYER_SQL))
    print("Phase 27 data layer bootstrapped successfully")


if __name__ == "__main__":
    main()
