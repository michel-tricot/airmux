"""runtime configuration publication

Revision ID: d1e2f3a4b5c6
Revises: c7d8e9f0a1b2
Create Date: 2026-08-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from control_plane.models.common.column_types import UTCDateTime

revision = "d1e2f3a4b5c6"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_configuration",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("desired_revision", sa.Integer(), nullable=False),
        sa.Column("published_revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["org.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("org_id"),
    )
    op.add_column("bundle", sa.Column("configuration_revision", sa.Integer(), server_default="0", nullable=False))
    op.alter_column("bundle", "configuration_revision", server_default=None)
    op.execute("INSERT INTO runtime_configuration (org_id, desired_revision, published_revision) SELECT id, 0, 0 FROM org")
    op.drop_column("bundle", "expires_at")


def downgrade() -> None:
    op.add_column("bundle", sa.Column("expires_at", UTCDateTime(), nullable=True))
    op.execute("UPDATE bundle SET expires_at = issued_at + INTERVAL '24 hours'")
    op.alter_column("bundle", "expires_at", nullable=False)
    op.drop_column("bundle", "configuration_revision")
    op.drop_table("runtime_configuration")
