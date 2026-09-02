"""require usage key uuid

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-09-01
"""

from __future__ import annotations

from uuid import UUID, uuid5

import sqlalchemy as sa
from alembic import op

revision = "e7f8a9b0c1d2"
down_revision = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None

LEGACY_INFERENCE_KEY_NAMESPACE = UUID("9f09b7c3-1424-5c04-a175-eac16b26b2a4")


def upgrade() -> None:
    connection = op.get_bind()
    key_ids = connection.execute(sa.text("SELECT DISTINCT key_id FROM usage_event")).scalars()
    for key_id in key_ids:
        try:
            UUID(key_id)
        except ValueError:
            connection.execute(
                sa.text("UPDATE usage_event SET key_id = :normalized WHERE key_id = :legacy"),
                {"normalized": str(uuid5(LEGACY_INFERENCE_KEY_NAMESPACE, key_id)), "legacy": key_id},
            )
    op.alter_column("usage_event", "key_id", existing_type=sa.String(), type_=sa.Uuid(), postgresql_using="key_id::uuid", nullable=False)


def downgrade() -> None:
    op.alter_column("usage_event", "key_id", existing_type=sa.Uuid(), type_=sa.String(), postgresql_using="key_id::text", nullable=False)
