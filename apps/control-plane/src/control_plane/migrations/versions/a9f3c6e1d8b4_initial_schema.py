"""initial schema

The tenancy model: users and orgs are instance-level, org_membership ties them, workspaces live
under an org and are named within it by an org-unique slug, workspace_membership's composite foreign keys make cross-org membership
structurally impossible (with a cascade evicting users whose org membership goes), and
inference keys live in workspaces with org_id kept consistent by a composite foreign key.

Management keys authenticate one principal and carry an explicit permission ceiling at an instance,
organization, or workspace scope. Roles on the principal and memberships provide standing
authority, so a key can attenuate authority but never create it. Data-plane instances retain the
organization scope of the key that heartbeats, or null for a global instance-scoped key.

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
from sqlalchemy.dialects import postgresql

from control_plane.models.audit import audit_trigger_ddl_v1, audit_trigger_drop_ddl_v1
from control_plane.models.bundle_input import bundle_input_trigger_ddl_v1, bundle_input_trigger_drop_ddl_v1
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.common.identified import UUIDV7_SHIM_DDL_V1, needs_uuidv7_shim
from control_plane.models.common.tombstone import touch_trigger_ddl_v1, touch_trigger_drop_ddl_v1

revision = "a9f3c6e1d8b4"
down_revision = None
branch_labels = None
depends_on = None

TOMBSTONED = (
    "management_key",
    "auth_identity",
    "auth_session",
    "cli_auth_request",
    "inference_key",
    "model",
    "org",
    "org_invitation",
    "org_membership",
    "playground_session",
    "policy",
    "provider",
    "provider_credential",
    "user",
    "workspace",
    "workspace_membership",
)

AUDITED = (
    ("inference_key", ("id",)),
    ("management_key", ("id",)),
    ("model", ("id",)),
    ("org", ("id",)),
    ("org_invitation", ("id",)),
    ("org_membership", ("user_id", "org_id")),
    ("playground_session", ("id",)),
    ("policy", ("id",)),
    ("provider", ("id",)),
    ("provider_credential", ("id",)),
    ("user", ("id",)),
    ("workspace", ("id",)),
    ("workspace_membership", ("user_id", "workspace_id")),
)

BUNDLE_INPUTS = (
    ("inference_key", "org", ()),
    ("model", "global", ()),
    ("playground_session", "org", ()),
    ("policy", "org", ()),
    ("provider", "global", ()),
    ("provider_credential", "nullable_org", ("status", "status_at")),
    ("workspace", "org", ()),
)


def upgrade() -> None:
    if needs_uuidv7_shim(op.get_bind()):
        op.execute(UUIDV7_SHIM_DDL_V1)
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
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
        "user",
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("instance_role", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("service_account", sa.Boolean(), nullable=False),
        sa.Column("managing_org_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("instance_role IS NULL OR instance_role IN ('owner', 'auditor', 'data_plane')", name="user_instance_role_valid"),
        sa.CheckConstraint(
            "managing_org_id IS NULL OR (service_account AND instance_role IS NULL)",
            name="user_managing_org_requires_org_scoped_service_account",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "org",
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("slug", postgresql.CITEXT(), nullable=False),
        sa.Column("personal_for", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["personal_for"],
            ["user.id"],
            name="org_personal_for_fkey",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("personal_for", name="org_personal_for_key"),
        sa.UniqueConstraint("slug", name="org_slug_key"),
    )
    op.create_index("ix_user_managing_org_id", "user", ["managing_org_id"], unique=False)
    op.create_foreign_key("user_managing_org_id_fkey", "user", "org", ["managing_org_id"], ["id"])
    op.create_table(
        "data_plane_instance",
        sa.Column("instance_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("version", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("bundle_id", sa.Uuid(), nullable=True),
        sa.Column("address", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("first_seen", UTCDateTime(), nullable=False),
        sa.Column("last_seen", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["org.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("instance_id"),
    )
    op.create_table(
        "provider",
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("name", postgresql.CITEXT(), nullable=False),
        sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("base_url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("icon", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("param_aliases", sa.JSON(), nullable=False),
        sa.Column("accepted_params", sa.JSON(), nullable=True),
        sa.Column("params_closed", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "usage_ingest_batch",
        sa.Column("ingest_id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("watermark", sa.Uuid(), nullable=False),
        sa.Column("received_at", UTCDateTime(), server_default=sa.text("clock_timestamp()"), nullable=False),
        sa.PrimaryKeyConstraint("ingest_id"),
        sa.UniqueConstraint("watermark"),
    )
    op.create_table(
        "gateway_request",
        sa.CheckConstraint(
            "(authentication_source = 'local' AND principal_type = 'local') OR "
            "(authentication_source IN ('inference_key', 'playground') AND principal_type IN ('human', 'service_account'))",
            name="gateway_request_attribution_valid",
        ),
        sa.CheckConstraint(
            "(terminal_event_id IS NULL AND terminal_ingest_id IS NULL AND finished_at IS NULL AND outcome IS NULL "
            "AND expected_attempts IS NULL AND latency_ms IS NULL) OR "
            "(terminal_event_id IS NOT NULL AND terminal_ingest_id IS NOT NULL AND finished_at IS NOT NULL AND outcome IS NOT NULL "
            "AND expected_attempts IS NOT NULL AND expected_attempts >= 0 AND latency_ms IS NOT NULL AND latency_ms >= 0)",
            name="gateway_request_terminal_all_or_none",
        ),
        sa.CheckConstraint("finished_at IS NULL OR request_started_at <= finished_at", name="gateway_request_timestamps_ordered"),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('succeeded', 'failed', 'denied', 'timeout', 'cancelled')",
            name="gateway_request_outcome_valid",
        ),
        sa.CheckConstraint("outcome <> 'succeeded' OR expected_attempts > 0", name="gateway_request_succeeded_was_routed"),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("request_started_at", UTCDateTime(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("key_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("authentication_source", sa.String(), nullable=False),
        sa.Column("authentication_label", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("principal_label", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("principal_type", sa.String(), nullable=False),
        sa.Column("workspace_label", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("requested_model_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("requested_capabilities", sa.ARRAY(sa.String()), nullable=False),
        sa.Column("bundle_id", sa.Uuid(), nullable=False),
        sa.Column("stream", sa.Boolean(), nullable=False),
        sa.Column("first_ingest_id", sa.BigInteger(), nullable=False),
        sa.Column("terminal_event_id", sa.Uuid(), nullable=True),
        sa.Column("terminal_ingest_id", sa.BigInteger(), nullable=True),
        sa.Column("finished_at", UTCDateTime(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=True),
        sa.Column("expected_attempts", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["first_ingest_id"], ["usage_ingest_batch.ingest_id"]),
        sa.ForeignKeyConstraint(["terminal_ingest_id"], ["usage_ingest_batch.ingest_id"]),
        sa.PrimaryKeyConstraint("request_id"),
        sa.UniqueConstraint("terminal_event_id"),
    )
    op.create_index("gateway_request_first_ingest_idx", "gateway_request", ["first_ingest_id"], unique=False)
    op.create_index("gateway_request_org_started_request_idx", "gateway_request", ["org_id", "request_started_at", "request_id"], unique=False)
    op.create_index(
        "gateway_request_org_workspace_started_request_idx",
        "gateway_request",
        ["org_id", "workspace_id", "request_started_at", "request_id"],
        unique=False,
    )
    op.create_table(
        "usage_event",
        sa.CheckConstraint(
            "(status = 'denied' AND token_usage_source = 'not_applicable') OR "
            "(status <> 'denied' AND token_usage_source IN ('provider', 'estimated', 'partial', 'unavailable'))",
            name="usage_event_token_usage_source_valid",
        ),
        sa.CheckConstraint(
            "(authentication_source = 'local' AND principal_type = 'local') OR "
            "(authentication_source IN ('inference_key', 'playground') AND principal_type IN ('human', 'service_account'))",
            name="usage_event_attribution_valid",
        ),
        sa.CheckConstraint(
            "(status = 'denied' AND attempt_index IS NULL AND attempt_started_at IS NULL "
            "AND credential_id IS NULL AND credential_scope IS NULL AND credential_name IS NULL "
            "AND input_price_per_mtok IS NULL AND output_price_per_mtok IS NULL "
            "AND cache_read_price_per_mtok IS NULL AND cache_write_price_per_mtok IS NULL AND cost_source = 'not_applicable' "
            "AND input_tokens = 0 AND output_tokens = 0 AND cache_read_tokens = 0 AND cache_write_tokens = 0 "
            "AND cost_usd = 0 AND cost_input_usd = 0 AND cost_output_usd = 0) OR "
            "(status <> 'denied' AND attempt_index > 0 AND attempt_started_at IS NOT NULL "
            "AND credential_id IS NOT NULL AND credential_scope IS NOT NULL AND credential_name IS NOT NULL "
            "AND input_price_per_mtok IS NOT NULL AND output_price_per_mtok IS NOT NULL "
            "AND cache_read_price_per_mtok IS NOT NULL AND cache_write_price_per_mtok IS NOT NULL "
            "AND ((token_usage_source = 'unavailable' AND cost_source = 'unavailable' "
            "AND input_tokens IS NULL AND output_tokens IS NULL AND cache_read_tokens IS NULL AND cache_write_tokens IS NULL "
            "AND cost_usd IS NULL AND cost_input_usd IS NULL AND cost_output_usd IS NULL) OR "
            "(token_usage_source IN ('provider', 'estimated', 'partial') AND cost_source = 'catalog_estimate' "
            "AND input_tokens IS NOT NULL AND output_tokens IS NOT NULL AND cache_read_tokens IS NOT NULL AND cache_write_tokens IS NOT NULL "
            "AND input_tokens >= cache_read_tokens + cache_write_tokens "
            "AND cost_usd IS NOT NULL AND cost_input_usd IS NOT NULL AND cost_output_usd IS NOT NULL "
            "AND cost_usd = cost_input_usd + cost_output_usd)))",
            name="usage_event_attempt_evidence_valid",
        ),
        sa.CheckConstraint(
            "request_started_at <= occurred_at AND (attempt_started_at IS NULL OR "
            "(request_started_at <= attempt_started_at AND attempt_started_at <= occurred_at))",
            name="usage_event_timestamps_ordered",
        ),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("ingest_id", sa.BigInteger(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("request_started_at", UTCDateTime(), nullable=False),
        sa.Column("attempt_started_at", UTCDateTime(), nullable=True),
        sa.Column("occurred_at", UTCDateTime(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("key_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("authentication_source", sa.String(), nullable=False),
        sa.Column("authentication_label", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("principal_label", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("principal_type", sa.String(), nullable=False),
        sa.Column("workspace_label", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("requested_model_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("requested_capabilities", sa.ARRAY(sa.String()), nullable=False),
        sa.Column("model_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("provider_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("bundle_id", sa.Uuid(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("token_usage_source", sa.String(), nullable=False),
        sa.Column("attempt_index", sa.Integer(), nullable=True),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("input_price_per_mtok", sa.Numeric(precision=16, scale=6), nullable=True),
        sa.Column("output_price_per_mtok", sa.Numeric(precision=16, scale=6), nullable=True),
        sa.Column("cache_read_price_per_mtok", sa.Numeric(precision=16, scale=6), nullable=True),
        sa.Column("cache_write_price_per_mtok", sa.Numeric(precision=16, scale=6), nullable=True),
        sa.Column("cost_source", sa.String(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=28, scale=12), nullable=True),
        sa.Column("cost_input_usd", sa.Numeric(precision=28, scale=12), nullable=True),
        sa.Column("cost_output_usd", sa.Numeric(precision=28, scale=12), nullable=True),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("stream", sa.Boolean(), nullable=False),
        sa.Column("credential_id", sa.Uuid(), nullable=True),
        sa.Column("credential_scope", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("credential_name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(["ingest_id"], ["usage_ingest_batch.ingest_id"]),
        sa.ForeignKeyConstraint(["request_id"], ["gateway_request.request_id"]),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("usage_event_ingest_id_idx", "usage_event", ["ingest_id"], unique=False)
    op.create_index("usage_event_org_occurred_event_idx", "usage_event", ["org_id", "occurred_at", "event_id"], unique=False)
    op.create_index("usage_event_org_event_idx", "usage_event", ["org_id", "event_id"], unique=False)
    op.create_index("usage_event_org_workspace_event_idx", "usage_event", ["org_id", "workspace_id", "event_id"], unique=False)
    op.create_index(
        "usage_event_org_request_attempt_key",
        "usage_event",
        ["org_id", "request_id", "attempt_index"],
        unique=True,
        postgresql_where=sa.text("attempt_index IS NOT NULL"),
    )
    op.create_index(
        "usage_event_org_request_denial_key",
        "usage_event",
        ["org_id", "request_id"],
        unique=True,
        postgresql_where=sa.text("attempt_index IS NULL"),
    )
    op.create_index(
        "usage_event_org_workspace_occurred_event_idx",
        "usage_event",
        ["org_id", "workspace_id", "occurred_at", "event_id"],
        unique=False,
    )
    op.create_table(
        "auth_identity",
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
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
        sa.Column("global_generation", sa.BigInteger(), nullable=False),
        sa.Column("org_generation", sa.BigInteger(), nullable=False),
        sa.Column("payload", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["org.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "global_generation", "org_generation", name="bundle_org_generation_key"),
    )
    op.create_table(
        "model",
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("upstream_model", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("egress_kind", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("input_price_per_mtok", sa.Numeric(precision=16, scale=6), nullable=False),
        sa.Column("output_price_per_mtok", sa.Numeric(precision=16, scale=6), nullable=False),
        sa.Column("cache_read_price_per_mtok", sa.Numeric(precision=16, scale=6), nullable=False),
        sa.Column("cache_write_price_per_mtok", sa.Numeric(precision=16, scale=6), nullable=False),
        sa.Column("context_window", sa.Integer(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("input_modalities", sa.JSON(), nullable=False),
        sa.Column("output_modalities", sa.JSON(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("parameter_support", sa.JSON(), nullable=False),
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
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("role", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.CheckConstraint("role IN ('owner', 'admin', 'member', 'data_plane')", name="org_membership_role_valid"),
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
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["approved_org_id"],
            ["org.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_code_hash"),
        sa.UniqueConstraint("poll_secret_hash"),
    )
    op.create_table(
        "workspace",
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("slug", postgresql.CITEXT(), nullable=False),
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
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("role", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.CheckConstraint("role IN ('admin', 'member', 'viewer')", name="workspace_membership_role_valid"),
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
    op.create_index("ix_workspace_membership_workspace_id", "workspace_membership", ["workspace_id"], unique=False)
    op.create_table(
        "management_key",
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("token_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("prefix", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("label", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=True),
        sa.Column("revoked_at", UTCDateTime(), nullable=True),
        sa.CheckConstraint("workspace_id IS NULL OR org_id IS NOT NULL", name="management_key_workspace_needs_org"),
        sa.ForeignKeyConstraint(["org_id"], ["org.id"]),
        sa.ForeignKeyConstraint(["parent_id"], ["management_key.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["workspace_id", "org_id"], ["workspace.id", "workspace.org_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_table(
        "inference_key",
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
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
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("provider_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", postgresql.CITEXT(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("status_at", UTCDateTime(), nullable=True),
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
        sa.UniqueConstraint(
            "org_id",
            "workspace_id",
            "provider_id",
            "name",
            name="provider_credential_scope_name_key",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_table(
        "org_invitation",
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
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
    op.create_table(
        "global_bundle_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("desired_generation", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO global_bundle_state (id, desired_generation) VALUES (1, 0)")
    op.create_table(
        "bundle_state",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("desired_generation", sa.BigInteger(), nullable=False),
        sa.Column("published_global_generation", sa.BigInteger(), nullable=False),
        sa.Column("published_org_generation", sa.BigInteger(), nullable=False),
        sa.Column("current_bundle_id", sa.Uuid(), nullable=True),
        sa.Column("failed_global_generation", sa.BigInteger(), nullable=True),
        sa.Column("failed_org_generation", sa.BigInteger(), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["current_bundle_id"], ["bundle.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["org_id"], ["org.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("org_id"),
    )
    op.create_table(
        "playground_session",
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
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
    op.create_table(
        "insecure_vault_secret",
        sa.Column("address", sa.String(length=64), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("address"),
    )
    op.create_table(
        "policy",
        sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["org.id"]),
        sa.ForeignKeyConstraint(["workspace_id", "org_id"], ["workspace.id", "workspace.org_id"]),
        sa.CheckConstraint("priority >= 0 AND priority <= 10000", name="policy_priority_valid"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("policy_workspace_priority_id_idx", "policy", ["workspace_id", "priority", "id"], unique=False)
    op.create_index(
        "policy_active_workspace_id_idx",
        "policy",
        ["workspace_id", "id"],
        unique=False,
        postgresql_where=sa.text("enabled"),
    )
    op.create_index(
        "policy_active_org_id_idx",
        "policy",
        ["org_id", "id"],
        unique=False,
        postgresql_where=sa.text("enabled"),
    )
    for table in TOMBSTONED:
        for statement in touch_trigger_ddl_v1(table):
            op.execute(statement)
    for table, pk_columns in AUDITED:
        for statement in audit_trigger_ddl_v1(table, pk_columns):
            op.execute(statement)
    for table, scope, ignored_columns in BUNDLE_INPUTS:
        for statement in bundle_input_trigger_ddl_v1(table, scope, ignored_columns):
            op.execute(statement)


def downgrade() -> None:
    for table, _, _ in BUNDLE_INPUTS:
        for statement in bundle_input_trigger_drop_ddl_v1(table):
            op.execute(statement)
    for table, _ in AUDITED:
        for statement in audit_trigger_drop_ddl_v1(table):
            op.execute(statement)
    for table in TOMBSTONED:
        for statement in touch_trigger_drop_ddl_v1(table):
            op.execute(statement)
    op.drop_table("insecure_vault_secret")
    op.drop_index("policy_active_org_id_idx", table_name="policy")
    op.drop_index("policy_active_workspace_id_idx", table_name="policy")
    op.drop_index("policy_workspace_priority_id_idx", table_name="policy")
    op.drop_table("policy")
    op.drop_table("playground_session")
    op.drop_table("bundle_state")
    op.drop_table("global_bundle_state")
    op.drop_index("org_invitation_pending_org_email_key", table_name="org_invitation")
    op.drop_table("org_invitation")
    op.drop_table("provider_credential")
    op.drop_table("inference_key")
    op.drop_index("ix_workspace_membership_workspace_id", table_name="workspace_membership")
    op.drop_table("workspace_membership")
    op.drop_table("management_key")
    op.drop_table("workspace")
    op.drop_table("cli_auth_request")
    op.drop_index(op.f("ix_org_membership_org_id"), table_name="org_membership")
    op.drop_table("org_membership")
    op.drop_table("model")
    op.drop_table("bundle")
    op.drop_table("auth_session")
    op.drop_table("auth_identity")
    op.drop_index("usage_event_org_request_denial_key", table_name="usage_event")
    op.drop_index("usage_event_org_request_attempt_key", table_name="usage_event")
    op.drop_index("usage_event_ingest_id_idx", table_name="usage_event")
    op.drop_index("usage_event_org_workspace_occurred_event_idx", table_name="usage_event")
    op.drop_index("usage_event_org_workspace_event_idx", table_name="usage_event")
    op.drop_index("usage_event_org_occurred_event_idx", table_name="usage_event")
    op.drop_index("usage_event_org_event_idx", table_name="usage_event")
    op.drop_table("usage_event")
    op.drop_index("gateway_request_org_workspace_started_request_idx", table_name="gateway_request")
    op.drop_index("gateway_request_org_started_request_idx", table_name="gateway_request")
    op.drop_index("gateway_request_first_ingest_idx", table_name="gateway_request")
    op.drop_table("gateway_request")
    op.drop_table("usage_ingest_batch")
    op.drop_table("provider")
    op.drop_table("data_plane_instance")
    op.drop_constraint("user_managing_org_id_fkey", "user", type_="foreignkey")
    op.drop_table("org")
    op.drop_table("user")
    op.drop_table("audit_log")
    op.execute("DROP EXTENSION IF EXISTS citext")
    if needs_uuidv7_shim(op.get_bind()):
        op.execute("DROP FUNCTION uuidv7()")
