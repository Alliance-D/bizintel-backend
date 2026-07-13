"""Add a non-guessable public token to app.location_reports and index created_at

Reports are shared by URL with no per-user auth, so exposing the sequential
BIGSERIAL id let anyone enumerate every report. Address each report by a random
token instead, and index created_at so the retention purge is cheap.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-14
"""
from __future__ import annotations

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE app.location_reports ADD COLUMN IF NOT EXISTS public_token TEXT;
        -- Backfill existing rows so none are left without a token (their old
        -- integer URLs are retired either way).
        UPDATE app.location_reports
           SET public_token = substr(md5(random()::text || id::text || clock_timestamp()::text), 1, 16)
         WHERE public_token IS NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_location_reports_public_token
            ON app.location_reports (public_token);
        CREATE INDEX IF NOT EXISTS idx_location_reports_created_at
            ON app.location_reports (created_at);
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS app.idx_location_reports_created_at;
        DROP INDEX IF EXISTS app.idx_location_reports_public_token;
        ALTER TABLE app.location_reports DROP COLUMN IF EXISTS public_token;
    """)
