"""model parameter support

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-08-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model", sa.Column("parameter_support", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False))
    op.alter_column("model", "parameter_support", server_default=None)


def downgrade() -> None:
    op.drop_column("model", "parameter_support")
