"""model modalities

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-08-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c5d6e7f8a9b0"
down_revision = "b4c5d6e7f8a9"
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
