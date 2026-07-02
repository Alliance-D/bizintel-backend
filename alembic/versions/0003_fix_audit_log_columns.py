"""Fix app.audit_log columns to match what the application actually writes/reads

The table as originally defined (user_id/user_email/user_role, no metadata
column) never matched app/services/audit_service.py's writer or
app/api/routes/security.py's reader (actor_user_id/actor_role/metadata) -
the audit trail has never actually worked. This migration corrects the
table to match the application code.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-02
"""
from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS app.audit_log;
        CREATE TABLE app.audit_log (
          id BIGSERIAL PRIMARY KEY,
          action TEXT NOT NULL,
          actor_user_id BIGINT,
          actor_role TEXT,
          entity_type TEXT,
          entity_id TEXT,
          request_id TEXT,
          ip_address INET,
          user_agent TEXT,
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_audit_log_created ON app.audit_log (created_at DESC);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS app.audit_log;
        CREATE TABLE app.audit_log (
          id BIGSERIAL PRIMARY KEY,
          action TEXT NOT NULL,
          user_id BIGINT,
          user_email TEXT,
          user_role TEXT,
          entity_type TEXT,
          entity_id TEXT,
          request_id TEXT,
          ip_address TEXT,
          user_agent TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
