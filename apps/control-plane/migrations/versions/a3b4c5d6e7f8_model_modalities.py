"""model modalities

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-08-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a3b4c5d6e7f8"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    default = sa.text("'[\"text\"]'::json")
    op.add_column("model", sa.Column("input_modalities", sa.JSON(), server_default=default, nullable=False))
    op.add_column("model", sa.Column("output_modalities", sa.JSON(), server_default=default, nullable=False))
    op.alter_column("model", "input_modalities", server_default=None)
    op.alter_column("model", "output_modalities", server_default=None)


def downgrade() -> None:
    op.drop_column("model", "output_modalities")
    op.drop_column("model", "input_modalities")
