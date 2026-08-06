"""auth tables

Human login lands: auth_identity (how a user proves who they are), auth_session (cookie
sessions), sso_connection (per-org OIDC issuer config), login_attempt (in-flight OIDC
authorizations).

Revision ID: 7c41d90ab3e1
Revises: 24a1527f53e2
Create Date: 2026-08-06 12:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
import sqlmodel
from alembic import op

from control_plane.models.mixins.tombstone import touch_trigger_ddl_v1

revision = "7c41d90ab3e1"
down_revision = "24a1527f53e2"
branch_labels = None
depends_on = None

TOMBSTONED = ("auth_identity", "auth_session", "sso_connection", "login_attempt")


def upgrade() -> None:
    op.create_table(
        "auth_identity",
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("provider", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("subject", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("secret_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "subject"),
    )
    op.create_table(
        "auth_session",
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("token_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_table(
        "sso_connection",
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("org_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("issuer", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("client_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("client_secret", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("email_domains", sa.JSON(), nullable=False),
        sa.Column("jit", sa.Boolean(), nullable=False),
        sa.Column("authorization_endpoint", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("token_endpoint", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("jwks_uri", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["org.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "login_attempt",
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("state", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("connection_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("nonce", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("code_verifier", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["sso_connection.id"],
        ),
        sa.PrimaryKeyConstraint("state"),
    )
    if op.get_bind().dialect.name == "sqlite":
        for table in TOMBSTONED:
            for statement in touch_trigger_ddl_v1(table):
                op.execute(statement)


def downgrade() -> None:
    op.drop_table("login_attempt")
    op.drop_table("sso_connection")
    op.drop_table("auth_session")
    op.drop_table("auth_identity")
