"""Add a per-model egress adapter override.

Revision ID: b1e2d3f4a5b6
Revises: a9f3c6e1d8b4
Create Date: 2026-08-17
"""

from alembic import op
import sqlalchemy as sa

revision = "b1e2d3f4a5b6"
down_revision = "a9f3c6e1d8b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model", sa.Column("egress_kind", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("model", "egress_kind")
