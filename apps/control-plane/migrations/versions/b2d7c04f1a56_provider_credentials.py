"""provider credentials

A provider API key an org or one of its workspaces brings, so a tenant can spend against their own
upstream account. The value is not here and neither is its location: it lives in the secret store,
addressed by fields this row already carries. A value column would be copied into audit_log by the
audit trigger, and a location column would be something a tenant could point somewhere it should
not go.

Scope is derived from which owner columns are set rather than stored, so a row cannot claim one
scope while carrying another's ownership. org_id is nullable because a platform credential belongs
to the instance; the check constraint covers what the composite foreign key cannot, since a MATCH
SIMPLE key with a null column is not checked at all.

Revision ID: b2d7c04f1a56
Revises: a9f3c6e1d8b4
Create Date: 2026-08-09
"""

from __future__ import annotations

import sqlalchemy as sa
import sqlmodel
from alembic import op

from control_plane.models.audit import audit_trigger_ddl_v1, audit_trigger_drop_ddl_v1
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.common.tombstone import touch_trigger_ddl_v1, touch_trigger_drop_ddl_v1

revision = "b2d7c04f1a56"
down_revision = "a9f3c6e1d8b4"
branch_labels = None
depends_on = None

TABLE = "provider_credential"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", UTCDateTime(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("fingerprint", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.CheckConstraint("workspace_id IS NULL OR org_id IS NOT NULL", name="provider_credential_workspace_needs_org"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["org.id"],
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["provider.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "org_id"],
            ["workspace.id", "workspace.org_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "workspace_id", "provider_id", "name", name="provider_credential_scope_name_key"),
    )
    for statement in touch_trigger_ddl_v1(TABLE):
        op.execute(statement)
    for statement in audit_trigger_ddl_v1(TABLE, ("id",)):
        op.execute(statement)


def downgrade() -> None:
    for statement in audit_trigger_drop_ddl_v1(TABLE):
        op.execute(statement)
    for statement in touch_trigger_drop_ddl_v1(TABLE):
        op.execute(statement)
    op.drop_table(TABLE)
