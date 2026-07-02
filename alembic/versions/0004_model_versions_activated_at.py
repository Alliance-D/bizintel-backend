"""Add activated_at to ml.model_versions

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-02
"""
from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE ml.model_versions ADD COLUMN IF NOT EXISTS activated_at TIMESTAMPTZ;
        UPDATE ml.model_versions SET activated_at = created_at WHERE is_active = TRUE AND activated_at IS NULL;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE ml.model_versions DROP COLUMN IF EXISTS activated_at;")
