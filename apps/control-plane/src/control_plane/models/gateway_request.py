from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, Column, Index, String, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Field

from contract import AuthenticationSource, GatewayRequestOutcome, PrincipalType
from contract.model_types import RequestCapability
from control_plane.db import current_session
from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.overview_report import (
    OverviewFreshnessOut,
    OverviewReportOut,
    OverviewReportQuery,
    ReportFact,
    UnknownReportWatermarkError,
    _OverviewReportQueryBase,
    build_overview_report,
    resolve_periods,
)


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

    @classmethod
    async def overview_report(
        cls,
        org_id: UUID,
        workspace_id: UUID | None,
        query: _OverviewReportQueryBase,
    ) -> OverviewReportOut:
        session = current_session()
        batch_statement = (
            text("SELECT ingest_id, watermark, received_at FROM usage_ingest_batch WHERE watermark = :watermark")
            if query.as_of is not None
            else text("SELECT ingest_id, watermark, received_at FROM usage_ingest_batch ORDER BY ingest_id DESC LIMIT 1")
        )
        batch = (await session.execute(batch_statement, {"watermark": query.as_of} if query.as_of is not None else {})).mappings().one_or_none()
        if query.as_of is not None and batch is None:
            raise UnknownReportWatermarkError
        if batch is None:
            received_at = (await session.execute(text("SELECT clock_timestamp()"))).scalar_one()
            freshness = OverviewFreshnessOut(watermark=None, received_at=received_at)
            periods = resolve_periods(query, received_at)
            return build_overview_report(query, freshness, periods, [])

        ingest_id = int(batch["ingest_id"])
        received_at = batch["received_at"]
        freshness = OverviewFreshnessOut(watermark=batch["watermark"], received_at=received_at)
        period_anchor = received_at if query.as_of is not None else (await session.execute(text("SELECT clock_timestamp()"))).scalar_one()
        periods = resolve_periods(query, period_anchor)
        workspace_filters = query.workspace if isinstance(query, OverviewReportQuery) else []
        statement = text(
            """
            SELECT
                gr.request_id,
                gr.request_started_at,
                gr.workspace_id,
                gr.workspace_label,
                gr.key_id,
                gr.authentication_label,
                gr.user_id,
                gr.principal_label,
                CASE WHEN gr.terminal_ingest_id <= :ingest_id THEN gr.outcome END AS outcome,
                CASE WHEN gr.terminal_ingest_id <= :ingest_id THEN gr.expected_attempts END AS expected_attempts,
                (
                    SELECT count(*)
                    FROM usage_event all_visible
                    WHERE all_visible.request_id = gr.request_id
                        AND all_visible.org_id = gr.org_id
                        AND all_visible.ingest_id <= :ingest_id
                        AND all_visible.attempt_index IS NOT NULL
                ) AS visible_attempts,
                ue.attempt_index,
                ue.model_id,
                ue.provider_id,
                ue.input_tokens,
                ue.output_tokens,
                ue.cache_read_tokens,
                ue.cache_write_tokens,
                ue.token_usage_source,
                ue.cost_source,
                ue.cost_usd
            FROM gateway_request gr
            LEFT JOIN usage_event ue
                ON ue.request_id = gr.request_id
                AND ue.org_id = gr.org_id
                AND ue.ingest_id <= :ingest_id
                AND (
                    (:model_filter_off AND :provider_filter_off)
                    OR (
                        ue.attempt_index IS NOT NULL
                        AND (:model_filter_off OR ue.model_id = ANY(CAST(:model AS text[])))
                        AND (:provider_filter_off OR ue.provider_id = ANY(CAST(:provider AS text[])))
                    )
                )
            WHERE gr.org_id = :org_id
                AND gr.first_ingest_id <= :ingest_id
                AND gr.request_started_at >= :period_start
                AND gr.request_started_at < :period_end
                AND (CAST(:workspace_id AS uuid) IS NULL OR gr.workspace_id = CAST(:workspace_id AS uuid))
                AND (:workspace_filter_off OR gr.workspace_id = ANY(CAST(:workspace AS uuid[])))
                AND (:principal_filter_off OR gr.user_id = ANY(CAST(:principal AS uuid[])))
                AND (:key_filter_off OR gr.key_id = ANY(CAST(:inference_key AS text[])))
                AND (
                    (:model_filter_off AND :provider_filter_off)
                    OR EXISTS (
                        SELECT 1
                        FROM usage_event visible
                        WHERE visible.request_id = gr.request_id
                            AND visible.org_id = gr.org_id
                            AND visible.ingest_id <= :ingest_id
                            AND visible.attempt_index IS NOT NULL
                            AND (:model_filter_off OR visible.model_id = ANY(CAST(:model AS text[])))
                            AND (:provider_filter_off OR visible.provider_id = ANY(CAST(:provider AS text[])))
                    )
                )
            ORDER BY gr.request_started_at, gr.request_id, ue.attempt_index
            """
        )
        parameters = {
            "org_id": org_id,
            "ingest_id": ingest_id,
            "period_start": periods.comparison.start_at,
            "period_end": periods.current.end_at,
            "workspace_id": workspace_id,
            "workspace_filter_off": not workspace_filters,
            "workspace": workspace_filters,
            "principal_filter_off": not query.principal,
            "principal": query.principal,
            "key_filter_off": not query.inference_key,
            "inference_key": query.inference_key,
            "model_filter_off": not query.model,
            "model": query.model,
            "provider_filter_off": not query.provider,
            "provider": query.provider,
        }
        rows = (await session.execute(statement, parameters)).mappings()
        facts = [ReportFact.model_validate(dict(row)) for row in rows]
        return build_overview_report(query, freshness, periods, facts)
