"""user service account flag

Revision ID: d5e8b90a17c2
Revises: c9f3a52d80e4
Create Date: 2026-08-04 22:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "d5e8b90a17c2"
down_revision = "c9f3a52d80e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(sa.Column("service_account", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("service_account")
