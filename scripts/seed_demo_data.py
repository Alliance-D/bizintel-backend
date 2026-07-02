"""Seed Phase 10 demo/readiness SQL into PostgreSQL.

Usage:
    python scripts/seed_demo_data.py

Requires DATABASE_URL in the environment.
"""
from pathlib import Path
import os
import psycopg2

ROOT = Path(__file__).resolve().parents[1]
SQL_FILE = ROOT / "backend" / "sql" / "014_demo_seed_and_final_views.sql"


def main() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required")
    sql = SQL_FILE.read_text(encoding="utf-8")
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    print(f"Applied {SQL_FILE}")


if __name__ == "__main__":
    main()
