"""remove bundle staleness

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-08-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from control_plane.models.common.column_types import UTCDateTime

revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("bundle", "expires_at")


def downgrade() -> None:
    op.add_column("bundle", sa.Column("expires_at", UTCDateTime(), nullable=True))
    op.execute("UPDATE bundle SET expires_at = issued_at + INTERVAL '24 hours'")
    op.alter_column("bundle", "expires_at", nullable=False)
