"""short-lived playground sessions

Revision ID: e1f2a3b4c5d6
Revises: d9e0f1a2b3c4
Create Date: 2026-08-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from control_plane.models.audit import audit_trigger_ddl_v1, audit_trigger_drop_ddl_v1
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.common.tombstone import touch_trigger_ddl_v1, touch_trigger_drop_ddl_v1

revision = "e1f2a3b4c5d6"
down_revision = "d9e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "playground_session",
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", UTCDateTime(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("credential_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["org.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id", "org_id"], ["workspace.id", "workspace.org_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("credential_id", name="playground_session_credential_id_key"),
        sa.UniqueConstraint("token_hash"),
    )
    for statement in touch_trigger_ddl_v1("playground_session"):
        op.execute(statement)
    for statement in audit_trigger_ddl_v1("playground_session", ("id",)):
        op.execute(statement)


def downgrade() -> None:
    for statement in audit_trigger_drop_ddl_v1("playground_session"):
        op.execute(statement)
    for statement in touch_trigger_drop_ddl_v1("playground_session"):
        op.execute(statement)
    op.drop_table("playground_session")
