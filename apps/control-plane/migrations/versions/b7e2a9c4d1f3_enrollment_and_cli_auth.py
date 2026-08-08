"""enrollment and cli auth

org.personal_for caps self-serve org creation at one per user; key labels become mandatory so
listings can say where a credential came from; cli_auth_request backs the device authorization
flow that mints CLI keys from a browser approval.

The label backfill rides on a server default that is dropped after the columns exist: ADD COLUMN
with a default rewrites rows without firing row triggers, so the audit trigger never sees an
unattributed write.

Revision ID: b7e2a9c4d1f3
Revises: f1a7c3d9e5b2
Create Date: 2026-08-07
"""

from __future__ import annotations

import sqlalchemy as sa
import sqlmodel
from alembic import op

from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.common.tombstone import touch_trigger_ddl_v1, touch_trigger_drop_ddl_v1

revision = "b7e2a9c4d1f3"
down_revision = "f1a7c3d9e5b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("org", sa.Column("personal_for", sa.Uuid(), nullable=True))
    op.create_unique_constraint("org_personal_for_key", "org", ["personal_for"])
    op.create_foreign_key("org_personal_for_fkey", "org", "user", ["personal_for"], ["id"])
    for table in ("management_key", "inference_key"):
        op.add_column(table, sa.Column("label", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="legacy"))
        op.alter_column(table, "label", server_default=None)
    op.create_table(
        "cli_auth_request",
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", UTCDateTime(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("user_code_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("poll_secret_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("client_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("requester", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("approved_user_id", sa.Uuid(), nullable=True),
        sa.Column("approved_org_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["approved_user_id"],
            ["user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["approved_org_id"],
            ["org.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_code_hash"),
        sa.UniqueConstraint("poll_secret_hash"),
    )
    for statement in touch_trigger_ddl_v1("cli_auth_request"):
        op.execute(statement)


def downgrade() -> None:
    for statement in touch_trigger_drop_ddl_v1("cli_auth_request"):
        op.execute(statement)
    op.drop_table("cli_auth_request")
    for table in ("management_key", "inference_key"):
        op.drop_column(table, "label")
    op.drop_constraint("org_personal_for_fkey", "org", type_="foreignkey")
    op.drop_constraint("org_personal_for_key", "org", type_="unique")
    op.drop_column("org", "personal_for")
