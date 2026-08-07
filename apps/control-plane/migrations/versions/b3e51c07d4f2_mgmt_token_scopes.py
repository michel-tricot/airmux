"""mgmt token scopes

Revision ID: b3e51c07d4f2
Revises: 7c41d90ab3e1
Create Date: 2026-08-06

NULL means unrestricted (the owning user's full authority), so existing tokens need no backfill.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b3e51c07d4f2"
down_revision = "7c41d90ab3e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mgmt_token", sa.Column("scopes", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("mgmt_token", "scopes")
