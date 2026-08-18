"""runtime configuration publication

Revision ID: d1e2f3a4b5c6
Revises: c7d8e9f0a1b2
Create Date: 2026-08-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

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


def downgrade() -> None:
    op.drop_column("bundle", "configuration_revision")
    op.drop_table("runtime_configuration")
