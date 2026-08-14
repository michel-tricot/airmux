"""Move cache pricing from provider multipliers to direct model prices

Revision ID: d8c0e3f4a1b2
Revises: a9f3c6e1d8b4
Create Date: 2026-08-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d8c0e3f4a1b2"
down_revision = "a9f3c6e1d8b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model", sa.Column("cache_read_price_per_mtok", sa.Float(), nullable=True))
    op.add_column("model", sa.Column("cache_write_price_per_mtok", sa.Float(), nullable=True))
    op.execute("SELECT set_config('app.user_id', 'migration', true)")
    op.execute(
        """
        UPDATE model
        SET cache_read_price_per_mtok = model.input_price_per_mtok * provider.cache_read_multiplier,
            cache_write_price_per_mtok = model.input_price_per_mtok * provider.cache_write_multiplier
        FROM provider
        WHERE model.provider_id = provider.id
        """
    )
    op.alter_column("model", "cache_read_price_per_mtok", nullable=False)
    op.alter_column("model", "cache_write_price_per_mtok", nullable=False)
    op.drop_column("provider", "cache_read_multiplier")
    op.drop_column("provider", "cache_write_multiplier")


def downgrade() -> None:
    op.add_column("provider", sa.Column("cache_read_multiplier", sa.Float(), server_default=sa.text("1.0"), nullable=False))
    op.add_column("provider", sa.Column("cache_write_multiplier", sa.Float(), server_default=sa.text("1.0"), nullable=False))
    op.alter_column("provider", "cache_read_multiplier", server_default=None)
    op.alter_column("provider", "cache_write_multiplier", server_default=None)
    op.drop_column("model", "cache_write_price_per_mtok")
    op.drop_column("model", "cache_read_price_per_mtok")
