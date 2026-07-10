"""Relax app.location_reports lat/lon to nullable for area-only/multi-location unified reports

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-10
"""
from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE app.location_reports ALTER COLUMN latitude DROP NOT NULL;
        ALTER TABLE app.location_reports ALTER COLUMN longitude DROP NOT NULL;
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE app.location_reports SET latitude = 0 WHERE latitude IS NULL;
        UPDATE app.location_reports SET longitude = 0 WHERE longitude IS NULL;
        ALTER TABLE app.location_reports ALTER COLUMN latitude SET NOT NULL;
        ALTER TABLE app.location_reports ALTER COLUMN longitude SET NOT NULL;
    """)
