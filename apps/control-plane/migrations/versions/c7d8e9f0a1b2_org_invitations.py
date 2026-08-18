"""org invitations

Revision ID: c7d8e9f0a1b2
Revises: a9f3c6e1d8b4
Create Date: 2026-08-17
"""

from __future__ import annotations

import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects import postgresql

from control_plane.models.audit import audit_trigger_ddl_v1, audit_trigger_drop_ddl_v1
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.common.tombstone import touch_trigger_ddl_v1, touch_trigger_drop_ddl_v1

revision = "c7d8e9f0a1b2"
down_revision = "a9f3c6e1d8b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "org_invitation",
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", UTCDateTime(), nullable=True),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("org_role", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("workspace_role", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("token_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("accepted_at", UTCDateTime(), nullable=True),
        sa.Column("accepted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", UTCDateTime(), nullable=True),
        sa.CheckConstraint("org_role IN ('admin', 'member')", name="org_invitation_org_role_valid"),
        sa.CheckConstraint(
            "workspace_role IS NULL OR workspace_role IN ('admin', 'member', 'viewer')",
            name="org_invitation_workspace_role_valid",
        ),
        sa.CheckConstraint(
            "(workspace_id IS NULL) = (workspace_role IS NULL)",
            name="org_invitation_workspace_grant_complete",
        ),
        sa.CheckConstraint(
            "accepted_at IS NULL OR revoked_at IS NULL",
            name="org_invitation_not_accepted_and_revoked",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["org.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["accepted_by_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "org_id"],
            ["workspace.id", "workspace.org_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "org_invitation_pending_org_email_key",
        "org_invitation",
        ["org_id", "email"],
        unique=True,
        postgresql_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"),
    )
    for statement in touch_trigger_ddl_v1("org_invitation"):
        op.execute(statement)
    for statement in audit_trigger_ddl_v1("org_invitation", ("id",)):
        op.execute(statement)


def downgrade() -> None:
    for statement in audit_trigger_drop_ddl_v1("org_invitation"):
        op.execute(statement)
    for statement in touch_trigger_drop_ddl_v1("org_invitation"):
        op.execute(statement)
    op.drop_index("org_invitation_pending_org_email_key", table_name="org_invitation")
    op.drop_table("org_invitation")
