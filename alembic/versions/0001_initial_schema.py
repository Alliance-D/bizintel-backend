"""Initial schema: raw/geo/curated/ml/app/field/meta layers, category profiles, feature catalog

Revision ID: 0001
Revises:
Create Date: 2026-07-02
"""
from __future__ import annotations

from alembic import op

from app.db.schema import CANONICAL_SCHEMA_SQL

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(CANONICAL_SCHEMA_SQL)


def downgrade() -> None:
    op.execute("""
        DROP SCHEMA IF EXISTS ml CASCADE;
        DROP SCHEMA IF EXISTS field CASCADE;
        DROP SCHEMA IF EXISTS curated CASCADE;
        DROP SCHEMA IF EXISTS geo CASCADE;
        DROP SCHEMA IF EXISTS raw CASCADE;
        DROP SCHEMA IF EXISTS meta CASCADE;
        DROP SCHEMA IF EXISTS app CASCADE;
    """)
