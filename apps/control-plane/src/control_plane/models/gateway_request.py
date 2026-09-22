from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, Column, Index, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Field

from contract import AuthenticationSource, GatewayRequestOutcome, PrincipalType
from contract.model_types import RequestCapability
from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime


class GatewayRequest(Record, table=True):
    __table_args__: ClassVar = (
        CheckConstraint(
            "(authentication_source = 'local' AND principal_type = 'local') OR "
            "(authentication_source IN ('inference_key', 'playground') AND principal_type IN ('human', 'service_account'))",
            name="gateway_request_attribution_valid",
        ),
        CheckConstraint(
            "(terminal_event_id IS NULL AND terminal_ingest_id IS NULL AND finished_at IS NULL AND outcome IS NULL "
            "AND expected_attempts IS NULL AND latency_ms IS NULL) OR "
            "(terminal_event_id IS NOT NULL AND terminal_ingest_id IS NOT NULL AND finished_at IS NOT NULL AND outcome IS NOT NULL "
            "AND expected_attempts IS NOT NULL AND expected_attempts >= 0 AND latency_ms IS NOT NULL AND latency_ms >= 0)",
            name="gateway_request_terminal_all_or_none",
        ),
        CheckConstraint("finished_at IS NULL OR request_started_at <= finished_at", name="gateway_request_timestamps_ordered"),
        CheckConstraint(
            "outcome IS NULL OR outcome IN ('succeeded', 'failed', 'denied', 'timeout', 'cancelled')",
            name="gateway_request_outcome_valid",
        ),
        CheckConstraint("outcome <> 'succeeded' OR expected_attempts > 0", name="gateway_request_succeeded_was_routed"),
        Index("gateway_request_org_started_request_idx", "org_id", "request_started_at", "request_id"),
        Index("gateway_request_org_workspace_started_request_idx", "org_id", "workspace_id", "request_started_at", "request_id"),
        Index("gateway_request_first_ingest_idx", "first_ingest_id"),
    )

    request_id: UUID = Field(primary_key=True)
    request_started_at: datetime = Field(sa_type=UTCDateTime)
    org_id: UUID
    workspace_id: UUID
    key_id: str
    authentication_source: AuthenticationSource = Field(sa_type=String)
    authentication_label: str
    user_id: UUID
    principal_label: str
    principal_type: PrincipalType = Field(sa_type=String)
    workspace_label: str
    requested_model_id: str
    requested_capabilities: list[RequestCapability] = Field(sa_column=Column(ARRAY(String), nullable=False))
    bundle_id: UUID
    stream: bool
    first_ingest_id: int = Field(foreign_key="usage_ingest_batch.ingest_id", sa_type=BigInteger)
    terminal_event_id: UUID | None = Field(default=None, unique=True)
    terminal_ingest_id: int | None = Field(default=None, foreign_key="usage_ingest_batch.ingest_id", sa_type=BigInteger)
    finished_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    outcome: GatewayRequestOutcome | None = Field(default=None, sa_type=String)
    expected_attempts: int | None = None
    latency_ms: int | None = None
