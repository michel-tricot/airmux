"""runtime configuration publication

Revision ID: d1e2f3a4b5c6
Revises: c7d8e9f0a1b2
Create Date: 2026-08-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from control_plane.models.runtime_configuration import (
    runtime_configuration_seed_trigger_ddl_v1,
    runtime_configuration_seed_trigger_drop_ddl_v1,
    runtime_configuration_trigger_ddl_v1,
    runtime_configuration_trigger_drop_ddl_v1,
)

revision = "d1e2f3a4b5c6"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None

INPUTS = (
    ("inference_key", "org", ("org_id", "workspace_id", "token_hash", "revoked")),
    (
        "model",
        "global",
        (
            "name",
            "provider_id",
            "upstream_model",
            "egress_kind",
            "input_price_per_mtok",
            "output_price_per_mtok",
            "cache_read_price_per_mtok",
            "cache_write_price_per_mtok",
            "context_window",
            "max_output_tokens",
            "capabilities",
        ),
    ),
    ("provider", "global", ("name", "kind", "base_url", "param_aliases", "accepted_params", "params_closed")),
    (
        "provider_credential",
        "nullable_org",
        ("org_id", "workspace_id", "provider_name", "name", "priority", "enabled", "version"),
    ),
)


def upgrade() -> None:
    op.create_table(
        "runtime_configuration",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("desired_revision", sa.Integer(), nullable=False),
        sa.Column("published_revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["org.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("org_id"),
    )
    op.add_column("bundle", sa.Column("configuration_revision", sa.Integer(), server_default="0", nullable=False))
    op.alter_column("bundle", "configuration_revision", server_default=None)
    op.execute("INSERT INTO runtime_configuration (org_id, desired_revision, published_revision) SELECT id, 0, 0 FROM org")
    for statement in runtime_configuration_seed_trigger_ddl_v1():
        op.execute(statement)
    for table, scope, columns in INPUTS:
        for statement in runtime_configuration_trigger_ddl_v1(table, scope, columns):
            op.execute(statement)


def downgrade() -> None:
    for table, _, _ in reversed(INPUTS):
        for statement in runtime_configuration_trigger_drop_ddl_v1(table):
            op.execute(statement)
    for statement in runtime_configuration_seed_trigger_drop_ddl_v1():
        op.execute(statement)
    op.drop_column("bundle", "configuration_revision")
    op.drop_table("runtime_configuration")
