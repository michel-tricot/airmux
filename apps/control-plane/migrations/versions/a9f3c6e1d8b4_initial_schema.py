"""initial schema

Consolidated on 2026-08-09 from the pre-release chain (initial schema, enrollment and cli auth,
workspaces, workspace slugs, provider credentials); nothing had deployed, so the chain had no
consumers. From first deployment on the chain is append-only: never squash again or edit a shipped
revision.

The tenancy model: users and orgs are instance-level, org_membership ties them, workspaces live
under an org and are named within it by an org-unique slug, workspace_membership's composite foreign keys make cross-org membership
structurally impossible (with a cascade evicting users whose org membership goes), and
inference keys live in workspaces with org_id kept consistent by a composite foreign key.

Credentials split by reach: management_key names its org and cannot omit it, instance_key carries
instance-wide authority for admins, and data_plane_instance registers against the instance with no
org of its own.

Provider credentials are the keys the gateway spends upstream, and provider_credential holds
everything about one except its value, which lives in the secret store. Scope is derived from which
owner columns are set rather than stored: both null is a platform key, org alone is an org key, and
both is a workspace key. org_id is therefore nullable, and the check constraint covers what the
composite foreign key cannot, since a MATCH SIMPLE key with a null column is not checked at all.

Server-minted ids default to uuidv7(), native on Postgres 18; on 16 and 17 the migration
detects the version and installs a pure-SQL equivalent (millisecond timestamp overlaid on
gen_random_uuid with the version bits set to 7) before any table references it. The default is
only the backstop for raw inserts; the ORM mints ids client-side through contract.uuid7.

Revision ID: a9f3c6e1d8b4
Revises:
Create Date: 2026-08-08
"""

from __future__ import annotations

import sqlalchemy as sa
import sqlmodel
from alembic import op

from control_plane.models.audit import audit_trigger_ddl_v1, audit_trigger_drop_ddl_v1
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.common.identified import UUIDV7_SHIM_DDL_V1, needs_uuidv7_shim
from control_plane.models.common.tombstone import touch_trigger_ddl_v1, touch_trigger_drop_ddl_v1

revision = "a9f3c6e1d8b4"
down_revision = None
branch_labels = None
depends_on = None

TOMBSTONED = (
    "org",
    "provider",
    "user",
    "inference_key",
    "auth_identity",
    "auth_session",
    "instance_key",
    "management_key",
    "model",
    "org_membership",
    "cli_auth_request",
    "workspace",
    "workspace_membership",
    "provider_credential",
)

AUDITED = (
    ("inference_key", ("id",)),
    ("instance_key", ("id",)),
    ("management_key", ("id",)),
    ("model", ("id",)),
    ("org", ("id",)),
    ("org_membership", ("user_id", "org_id")),
    ("provider", ("id",)),
    ("provider_credential", ("id",)),
    ("user", ("id",)),
    ("workspace", ("id",)),
    ("workspace_membership", ("user_id", "workspace_id")),
)


def upgrade() -> None:
    if needs_uuidv7_shim(op.get_bind()):
        op.execute(UUIDV7_SHIM_DDL_V1)
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("table_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("record_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("action", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("occurred_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "data_plane_instance",
        sa.Column("instance_id", sa.Uuid(), nullable=False),
        sa.Column("version", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("bundle_id", sa.Uuid(), nullable=True),
        sa.Column("address", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("first_seen", UTCDateTime(), nullable=False),
        sa.Column("last_seen", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("instance_id"),
    )
    op.create_table(
        "user",
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", UTCDateTime(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("email", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("instance_admin", sa.Boolean(), nullable=False),
        sa.Column("service_account", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "org",
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", UTCDateTime(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("personal_for", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["personal_for"],
            ["user.id"],
            name="org_personal_for_fkey",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("personal_for", name="org_personal_for_key"),
    )
    op.create_table(
        "provider",
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", UTCDateTime(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("base_url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("cache_read_multiplier", sa.Float(), nullable=False),
        sa.Column("cache_write_multiplier", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "usage_event",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", UTCDateTime(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("key_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("model_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("provider_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("bundle_id", sa.Uuid(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("cost_input_usd", sa.Float(), nullable=False),
        sa.Column("cost_output_usd", sa.Float(), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("stream", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_table(
        "auth_identity",
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", UTCDateTime(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
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
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", UTCDateTime(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("absolute_expires_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_table(
        "bundle",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("issued_at", UTCDateTime(), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("payload", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("signature", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("signing_key_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["org.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "management_key",
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", UTCDateTime(), nullable=True),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("prefix", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=True),
        sa.Column("label", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["org.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_table(
        "instance_key",
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", UTCDateTime(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("prefix", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=True),
        sa.Column("label", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_table(
        "model",
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", UTCDateTime(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("upstream_model", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("input_price_per_mtok", sa.Float(), nullable=False),
        sa.Column("output_price_per_mtok", sa.Float(), nullable=False),
        sa.Column("context_window", sa.Integer(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["provider.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "org_membership",
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", UTCDateTime(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["org.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("user_id", "org_id"),
    )
    op.create_index(op.f("ix_org_membership_org_id"), "org_membership", ["org_id"], unique=False)
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
    op.create_table(
        "workspace",
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", UTCDateTime(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("slug", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["org.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "org_id", name="workspace_id_org_id_key"),
        sa.UniqueConstraint("org_id", "slug", name="workspace_org_id_slug_key"),
    )
    op.create_table(
        "workspace_membership",
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", UTCDateTime(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "org_id"],
            ["workspace.id", "workspace.org_id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "org_id"],
            ["org_membership.user_id", "org_membership.org_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "workspace_id"),
    )
    op.create_table(
        "inference_key",
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", UTCDateTime(), nullable=True),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("prefix", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("label", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["org.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "org_id"],
            ["workspace.id", "workspace.org_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_table(
        "provider_credential",
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
    for table in TOMBSTONED:
        for statement in touch_trigger_ddl_v1(table):
            op.execute(statement)
    for table, pk_columns in AUDITED:
        for statement in audit_trigger_ddl_v1(table, pk_columns):
            op.execute(statement)


def downgrade() -> None:
    for table, _ in AUDITED:
        for statement in audit_trigger_drop_ddl_v1(table):
            op.execute(statement)
    for table in TOMBSTONED:
        for statement in touch_trigger_drop_ddl_v1(table):
            op.execute(statement)
    op.drop_table("provider_credential")
    op.drop_table("inference_key")
    op.drop_table("workspace_membership")
    op.drop_table("workspace")
    op.drop_table("cli_auth_request")
    op.drop_index(op.f("ix_org_membership_org_id"), table_name="org_membership")
    op.drop_table("org_membership")
    op.drop_table("model")
    op.drop_table("instance_key")
    op.drop_table("management_key")
    op.drop_table("bundle")
    op.drop_table("auth_session")
    op.drop_table("auth_identity")
    op.drop_table("usage_event")
    op.drop_table("provider")
    op.drop_table("org")
    op.drop_table("user")
    op.drop_table("data_plane_instance")
    op.drop_table("audit_log")
    if needs_uuidv7_shim(op.get_bind()):
        op.execute("DROP FUNCTION uuidv7()")
