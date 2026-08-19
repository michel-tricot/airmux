"""organization-managed service accounts

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
    op.add_column("user", sa.Column("managing_org_id", sa.Uuid(), nullable=True))
    op.create_index("ix_user_managing_org_id", "user", ["managing_org_id"], unique=False)
    op.create_foreign_key("user_managing_org_id_fkey", "user", "org", ["managing_org_id"], ["id"])
    op.create_check_constraint(
        "user_managing_org_requires_org_scoped_service_account",
        "user",
        "managing_org_id IS NULL OR (service_account AND instance_role IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("user_managing_org_requires_org_scoped_service_account", "user", type_="check")
    op.drop_constraint("user_managing_org_id_fkey", "user", type_="foreignkey")
    op.drop_index("ix_user_managing_org_id", table_name="user")
    op.drop_column("user", "managing_org_id")
