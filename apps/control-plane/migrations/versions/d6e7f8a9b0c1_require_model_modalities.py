"""require model modalities

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-09-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d6e7f8a9b0c1"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("SELECT set_config('app.user_id', 'migration:d6e7f8a9b0c1', true)"))
    connection.execute(sa.text("UPDATE model SET input_modalities = '[\"text\"]'::json WHERE input_modalities IS NULL"))
    connection.execute(sa.text("UPDATE model SET output_modalities = '[\"text\"]'::json WHERE output_modalities IS NULL"))
    op.alter_column("model", "input_modalities", existing_type=sa.JSON(), nullable=False)
    op.alter_column("model", "output_modalities", existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    op.alter_column("model", "output_modalities", existing_type=sa.JSON(), nullable=True)
    op.alter_column("model", "input_modalities", existing_type=sa.JSON(), nullable=True)
