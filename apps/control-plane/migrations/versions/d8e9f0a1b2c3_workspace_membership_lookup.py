"""workspace membership lookup

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-08-17
"""

from __future__ import annotations

from alembic import op

revision = "d8e9f0a1b2c3"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_workspace_membership_workspace_id", "workspace_membership", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_workspace_membership_workspace_id", table_name="workspace_membership")
