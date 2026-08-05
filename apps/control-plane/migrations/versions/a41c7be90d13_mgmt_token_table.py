"""mgmt token table

Revision ID: a41c7be90d13
Revises: 5fcd0d00191c
Create Date: 2026-08-04 18:20:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
import sqlmodel
from alembic import op


revision = "a41c7be90d13"
down_revision = "5fcd0d00191c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mgmttoken",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("org_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("mgmttoken")
