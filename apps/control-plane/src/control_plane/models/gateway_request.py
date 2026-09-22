from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Literal, cast
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, Column, Index, String, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Field

import control_plane.models.request_report as request_report_module
from contract import AuthenticationSource, GatewayRequestOutcome, PrincipalType, TokenUsageSource, UsdAmount
from contract.model_types import RequestCapability
from control_plane.db import current_session
from control_plane.models.common import InvalidCursorError
from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.overview_report import (
    InvalidReportSnapshotError,
    OverviewFreshnessOut,
    OverviewPeriodOut,
    OverviewReportOut,
    OverviewReportQuery,
    ReportFact,
    ReportSnapshotV1,
    _OverviewReportQueryBase,
    build_overview_report,
    decode_report_snapshot,
    encode_report_snapshot,
    resolve_periods,
)
from control_plane.models.request_report import (
    DeniedRequestEvidenceOut,
    GatewayRequestCsvExportOut,
    GatewayRequestDetailOut,
    GatewayRequestPageOut,
    GatewayRequestReportOut,
    ObservedRequestAttemptOut,
    OrgRequestExportQuery,
    OrgRequestReportQuery,
    RequestAsOfQuery,
    RequestAttemptFact,
    RequestCostAnchor,
    RequestCursorAnchor,
    RequestCursorV1,
    RequestExportTooLargeError,
    RequestLatencyAnchor,
    RequestSort,
    RequestStartedAtAnchor,
    RequestTokensAnchor,
    SortDirection,
    UnavailableRequestAttemptOut,
    WorkspaceRequestExportQuery,
    WorkspaceRequestReportQuery,
    build_request_accounting,
    build_request_csv,
    decode_request_cursor,
    encode_request_cursor,
    request_query_fingerprint,
    validate_request_cursor,
)


@dataclass(frozen=True)
class _RequestCutoff:
    ingest_id: int
    freshness: OverviewFreshnessOut
    snapshot: ReportSnapshotV1


@dataclass(frozen=True)
class _RequestPageContext:
    cutoff: _RequestCutoff
    period: OverviewPeriodOut
    cursor: RequestCursorV1 | None


type _RequestFilterQuery = OrgRequestExportQuery | WorkspaceRequestExportQuery
type _RequestPageQuery = OrgRequestReportQuery | WorkspaceRequestReportQuery


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
        cutoff = await _report_cutoff(org_id, workspace_id, query.as_of)
        if cutoff.ingest_id == 0:
            periods = resolve_periods(query, cutoff.snapshot.resolved_at)
            return build_overview_report(query, cutoff.freshness, periods, [])
        ingest_id = cutoff.ingest_id
        freshness = cutoff.freshness
        periods = resolve_periods(query, cutoff.snapshot.resolved_at)
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
                ue.credential_id,
                ue.credential_scope,
                ue.credential_name,
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

    @classmethod
    async def request_page(
        cls,
        org_id: UUID,
        workspace_id: UUID | None,
        query: _RequestPageQuery,
    ) -> GatewayRequestPageOut:
        context = await _request_page_context(query, org_id, workspace_id)
        if context.cutoff.ingest_id == 0:
            return GatewayRequestPageOut(
                freshness=context.cutoff.freshness,
                period=context.period,
                items=[],
                page={"next_cursor": None},
            )
        facts = await _request_facts(
            org_id,
            workspace_id,
            query,
            context,
            query.limit + 1,
        )
        visible = facts[: query.limit]
        items = await _request_items(org_id, context.cutoff.ingest_id, visible)
        next_cursor = None
        if len(facts) > query.limit:
            anchor = _cursor_anchor(visible[-1], query.sort)
            next_cursor = encode_request_cursor(
                RequestCursorV1(
                    as_of=context.cutoff.freshness.as_of,
                    sort=query.sort,
                    direction=query.direction,
                    anchor=anchor,
                    fingerprint=request_query_fingerprint(query, org_id, workspace_id, context.period),
                )
            )
        return GatewayRequestPageOut(
            freshness=context.cutoff.freshness,
            period=context.period,
            items=items,
            page={"next_cursor": next_cursor},
        )

    @classmethod
    async def request_detail(
        cls,
        org_id: UUID,
        workspace_id: UUID | None,
        request_id: UUID,
        query: RequestAsOfQuery,
    ) -> GatewayRequestDetailOut | None:
        cutoff = await _report_cutoff(org_id, workspace_id, query.as_of)
        if cutoff.ingest_id == 0:
            return None
        statement = text(
            """
            SELECT
                gr.*,
                CASE WHEN gr.terminal_ingest_id <= :ingest_id THEN gr.terminal_event_id END AS visible_terminal_event_id,
                CASE WHEN gr.terminal_ingest_id <= :ingest_id THEN gr.finished_at END AS visible_finished_at,
                CASE WHEN gr.terminal_ingest_id <= :ingest_id THEN gr.outcome END AS visible_outcome,
                CASE WHEN gr.terminal_ingest_id <= :ingest_id THEN gr.expected_attempts END AS visible_expected_attempts,
                CASE WHEN gr.terminal_ingest_id <= :ingest_id THEN gr.latency_ms END AS visible_latency_ms
            FROM gateway_request gr
            WHERE gr.org_id = :org_id
                AND gr.request_id = :request_id
                AND gr.first_ingest_id <= :ingest_id
                AND (CAST(:workspace_id AS uuid) IS NULL OR gr.workspace_id = CAST(:workspace_id AS uuid))
            """
        )
        fact = (
            (
                await current_session().execute(
                    statement,
                    {"org_id": org_id, "workspace_id": workspace_id, "request_id": request_id, "ingest_id": cutoff.ingest_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if fact is None:
            return None
        request = (await _request_items(org_id, cutoff.ingest_id, [dict(fact)]))[0]
        return GatewayRequestDetailOut(freshness=cutoff.freshness, request=request)

    @classmethod
    async def request_export(
        cls,
        org_id: UUID,
        workspace_id: UUID | None,
        query: _RequestFilterQuery,
    ) -> GatewayRequestCsvExportOut:
        cutoff = await _report_cutoff(org_id, workspace_id, query.as_of)
        period = resolve_periods(query, cutoff.snapshot.resolved_at).current
        context = _RequestPageContext(cutoff=cutoff, period=period, cursor=None)
        if cutoff.ingest_id == 0:
            csv_text = build_request_csv([])
            return GatewayRequestCsvExportOut(
                filename="airmux-requests.csv",
                row_count=0,
                freshness=cutoff.freshness,
                period=period,
                csv=csv_text,
            )
        facts = await _request_facts(
            org_id,
            workspace_id,
            query,
            context,
            _export_row_limit() + 1,
        )
        if len(facts) > _export_row_limit():
            raise RequestExportTooLargeError
        if (
            sum(cast("int", fact["visible_attempts"]) + cast("int", fact["visible_denials"]) for fact in facts)
            > request_report_module.MAX_EXPORT_EVIDENCE
        ):
            raise RequestExportTooLargeError
        items = await _request_items(org_id, cutoff.ingest_id, facts)
        csv_text = build_request_csv(items)
        return GatewayRequestCsvExportOut(
            filename="airmux-requests.csv",
            row_count=len(items),
            freshness=cutoff.freshness,
            period=period,
            csv=csv_text,
        )


async def _database_now() -> datetime:
    return (await current_session().execute(text("SELECT clock_timestamp()"))).scalar_one()


async def _report_cutoff(org_id: UUID, workspace_id: UUID | None, as_of: str | None) -> _RequestCutoff:
    if as_of is None:
        resolved_at = await _database_now()
        snapshot = None
    else:
        snapshot = decode_report_snapshot(as_of)
        if snapshot.org_id != org_id or snapshot.workspace_id != workspace_id:
            raise InvalidReportSnapshotError
        resolved_at = snapshot.resolved_at
        if snapshot.watermark is None:
            return _RequestCutoff(
                ingest_id=0,
                freshness=OverviewFreshnessOut(as_of=as_of, watermark=None, received_at=None),
                snapshot=snapshot,
            )
    watermark_clause = "" if snapshot is None else "WHERE batch.watermark = :watermark"
    statement = text(
        """
        WITH relevant AS (
            SELECT first_ingest_id AS ingest_id
            FROM gateway_request
            WHERE org_id = :org_id
                AND (CAST(:workspace_id AS uuid) IS NULL OR workspace_id = CAST(:workspace_id AS uuid))
            UNION
            SELECT terminal_ingest_id AS ingest_id
            FROM gateway_request
            WHERE org_id = :org_id
                AND terminal_ingest_id IS NOT NULL
                AND (CAST(:workspace_id AS uuid) IS NULL OR workspace_id = CAST(:workspace_id AS uuid))
            UNION
            SELECT ingest_id
            FROM usage_event
            WHERE org_id = :org_id
                AND (CAST(:workspace_id AS uuid) IS NULL OR workspace_id = CAST(:workspace_id AS uuid))
        )
        SELECT batch.ingest_id, batch.watermark, batch.received_at
        FROM usage_ingest_batch batch
        JOIN relevant ON relevant.ingest_id = batch.ingest_id
        __WATERMARK__
        ORDER BY batch.ingest_id DESC
        LIMIT 1
        """.replace("__WATERMARK__", watermark_clause)
    )
    parameters = {
        "org_id": org_id,
        "workspace_id": workspace_id,
        **({"watermark": snapshot.watermark} if snapshot is not None else {}),
    }
    batch = (await current_session().execute(statement, parameters)).mappings().one_or_none()
    if snapshot is not None and batch is None:
        raise InvalidReportSnapshotError
    if batch is None:
        snapshot = ReportSnapshotV1(watermark=None, resolved_at=resolved_at, org_id=org_id, workspace_id=workspace_id)
        as_of = encode_report_snapshot(snapshot)
        return _RequestCutoff(
            ingest_id=0,
            freshness=OverviewFreshnessOut(as_of=as_of, watermark=None, received_at=None),
            snapshot=snapshot,
        )
    snapshot = snapshot or ReportSnapshotV1(
        watermark=batch["watermark"],
        resolved_at=resolved_at,
        org_id=org_id,
        workspace_id=workspace_id,
    )
    as_of = encode_report_snapshot(snapshot)
    return _RequestCutoff(
        ingest_id=int(batch["ingest_id"]),
        freshness=OverviewFreshnessOut(as_of=as_of, watermark=batch["watermark"], received_at=batch["received_at"]),
        snapshot=snapshot,
    )


async def _request_page_context(
    query: _RequestPageQuery,
    org_id: UUID,
    workspace_id: UUID | None,
) -> _RequestPageContext:
    cursor = decode_request_cursor(query.cursor) if query.cursor is not None else None
    if cursor is not None:
        try:
            cutoff = await _report_cutoff(org_id, workspace_id, cursor.as_of)
        except InvalidReportSnapshotError as error:
            raise InvalidCursorError from error
        period = resolve_periods(query, cutoff.snapshot.resolved_at).current
        validate_request_cursor(cursor, query, org_id, workspace_id, period)
        return _RequestPageContext(cutoff=cutoff, period=period, cursor=cursor)
    cutoff = await _report_cutoff(org_id, workspace_id, query.as_of)
    return _RequestPageContext(cutoff=cutoff, period=resolve_periods(query, cutoff.snapshot.resolved_at).current, cursor=None)


def _literal_search_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _filter_clauses(
    org_id: UUID,
    workspace_id: UUID | None,
    query: _RequestFilterQuery,
    ingest_id: int,
    period: OverviewPeriodOut,
) -> tuple[list[str], dict[str, object]]:
    clauses = [
        "gr.org_id = :org_id",
        "gr.first_ingest_id <= :ingest_id",
        "gr.request_started_at >= :period_start",
        "gr.request_started_at < :period_end",
        "(CAST(:workspace_id AS uuid) IS NULL OR gr.workspace_id = CAST(:workspace_id AS uuid))",
    ]
    parameters: dict[str, object] = {
        "org_id": org_id,
        "workspace_id": workspace_id,
        "ingest_id": ingest_id,
        "period_start": period.start_at,
        "period_end": period.end_at,
    }
    workspace_filters = query.workspace if isinstance(query, OrgRequestExportQuery) else []
    filters = (
        ("workspace", workspace_filters, "gr.workspace_id = ANY(CAST(:workspace AS uuid[]))"),
        ("principal", query.principal, "gr.user_id = ANY(CAST(:principal AS uuid[]))"),
        ("inference_key", query.inference_key, "gr.key_id = ANY(CAST(:inference_key AS text[]))"),
    )
    for name, values, clause in filters:
        if values:
            clauses.append(clause)
            parameters[name] = values
    if query.model or query.provider or query.provider_credential:
        credential_ids = [value for value in query.provider_credential if isinstance(value, UUID)]
        includes_unattributed = "unattributed" in query.provider_credential
        attempt_filters = [
            "visible.request_id = gr.request_id",
            "visible.org_id = gr.org_id",
            "visible.ingest_id <= :ingest_id",
            "visible.attempt_index IS NOT NULL",
        ]
        if query.model:
            attempt_filters.append("visible.model_id = ANY(CAST(:model AS text[]))")
            parameters["model"] = query.model
        if query.provider:
            attempt_filters.append("visible.provider_id = ANY(CAST(:provider AS text[]))")
            parameters["provider"] = query.provider
        selectors = []
        if not query.provider_credential or credential_ids:
            if credential_ids:
                attempt_filters.append("visible.credential_id = ANY(CAST(:provider_credential AS uuid[]))")
                parameters["provider_credential"] = credential_ids
            selectors.append(
                f"EXISTS (SELECT 1 FROM usage_event visible WHERE {' AND '.join(attempt_filters)})"  # noqa: S608 fixed query clauses
            )
        if includes_unattributed and not query.model and not query.provider:
            selectors.append(
                """NOT EXISTS (
                    SELECT 1 FROM usage_event routed
                    WHERE routed.request_id = gr.request_id
                        AND routed.org_id = gr.org_id
                        AND routed.ingest_id <= :ingest_id
                        AND routed.attempt_index IS NOT NULL
                )"""
            )
        clauses.append(f"({' OR '.join(selectors)})" if selectors else "FALSE")
    if query.search is not None:
        parameters["search"] = _literal_search_pattern(query.search)
        clauses.append(
            """(
                CAST(gr.request_id AS text) ILIKE :search ESCAPE '\\'
                OR CAST(gr.workspace_id AS text) ILIKE :search ESCAPE '\\'
                OR gr.workspace_label ILIKE :search ESCAPE '\\'
                OR CAST(gr.user_id AS text) ILIKE :search ESCAPE '\\'
                OR gr.principal_label ILIKE :search ESCAPE '\\'
                OR gr.key_id ILIKE :search ESCAPE '\\'
                OR gr.authentication_label ILIKE :search ESCAPE '\\'
                OR gr.requested_model_id ILIKE :search ESCAPE '\\'
                OR EXISTS (
                    SELECT 1 FROM usage_event searched
                    WHERE searched.request_id = gr.request_id
                        AND searched.org_id = gr.org_id
                        AND searched.ingest_id <= :ingest_id
                        AND (
                            searched.model_id ILIKE :search ESCAPE '\\'
                            OR searched.provider_id ILIKE :search ESCAPE '\\'
                            OR CAST(searched.credential_id AS text) ILIKE :search ESCAPE '\\'
                            OR searched.credential_name ILIKE :search ESCAPE '\\'
                        )
                )
            )"""
        )
    return clauses, parameters


def _confidence_sql() -> str:
    return """
        CASE
            WHEN visible_expected_attempts = 0 AND visible_attempts = 0 THEN 'not_applicable'
            WHEN visible_attempts = 0 THEN 'unavailable'
            WHEN unavailable_attempts > 0 THEN 'unavailable'
            WHEN visible_outcome IS NULL OR visible_attempts <> visible_expected_attempts THEN 'partial'
            WHEN partial_attempts > 0 THEN 'partial'
            WHEN estimated_attempts > 0 THEN 'estimated'
            ELSE 'provider'
        END
    """


def _keyset_clause(cursor: RequestCursorV1 | None, parameters: dict[str, object]) -> str:
    if cursor is None:
        return ""
    anchor = cursor.anchor
    parameters["anchor_request_id"] = anchor.request_id
    parameters["anchor_started_at"] = anchor.request_started_at
    comparison = ">" if cursor.direction is SortDirection.asc else "<"
    if isinstance(anchor, RequestStartedAtAnchor):
        return f"AND (request_started_at, request_id) {comparison} (:anchor_started_at, :anchor_request_id)"
    if isinstance(anchor, RequestCostAnchor):
        parameters["anchor_cost"] = anchor.known_cost_usd
        return f"AND (known_cost_usd, request_started_at, request_id) {comparison} (:anchor_cost, :anchor_started_at, :anchor_request_id)"
    if isinstance(anchor, RequestTokensAnchor):
        parameters["anchor_tokens"] = anchor.known_tokens
        return f"AND (known_tokens, request_started_at, request_id) {comparison} (:anchor_tokens, :anchor_started_at, :anchor_request_id)"
    parameters["anchor_null_rank"] = anchor.null_rank
    parameters["anchor_latency"] = anchor.latency_ms
    return f"""AND (
        latency_null_rank > :anchor_null_rank
        OR (
            latency_null_rank = :anchor_null_rank
            AND (
                (CAST(:anchor_latency AS bigint) IS NOT NULL AND (visible_latency_ms, request_started_at, request_id) {comparison}
                    (CAST(:anchor_latency AS bigint), :anchor_started_at, :anchor_request_id))
                OR (CAST(:anchor_latency AS bigint) IS NULL AND (request_started_at, request_id) {comparison}
                    (:anchor_started_at, :anchor_request_id))
            )
        )
    )"""


def _order_sql(query: _RequestFilterQuery) -> str:
    direction = query.direction.value.upper()
    if query.sort.value == "latency_ms":
        return f"latency_null_rank ASC, visible_latency_ms {direction} NULLS LAST, request_started_at {direction}, request_id {direction}"
    return f"{query.sort.value} {direction}, request_started_at {direction}, request_id {direction}"


async def _request_facts(
    org_id: UUID,
    workspace_id: UUID | None,
    query: _RequestFilterQuery,
    context: _RequestPageContext,
    result_limit: int,
) -> list[dict[str, object]]:
    clauses, parameters = _filter_clauses(org_id, workspace_id, query, context.cutoff.ingest_id, context.period)
    parameters["result_limit"] = result_limit
    outer_clauses = []
    if query.outcome:
        outer_clauses.append("COALESCE(visible_outcome, 'pending') = ANY(CAST(:outcome AS text[]))")
        parameters["outcome"] = query.outcome
    if query.confidence:
        outer_clauses.append("confidence = ANY(CAST(:confidence AS text[]))")
        parameters["confidence"] = query.confidence
    keyset = _keyset_clause(context.cursor, parameters)
    outer_where = " AND ".join(outer_clauses)
    if outer_where:
        outer_where = f"WHERE {outer_where}"
    if keyset:
        outer_where = f"{outer_where} {keyset}" if outer_where else f"WHERE {keyset.removeprefix('AND ')}"
    request_sql = """
        WITH aggregated AS (
            SELECT
                gr.request_id,
                gr.request_started_at,
                gr.org_id,
                gr.workspace_id,
                gr.key_id,
                gr.authentication_source,
                gr.authentication_label,
                gr.user_id,
                gr.principal_label,
                gr.principal_type,
                gr.workspace_label,
                gr.requested_model_id,
                gr.requested_capabilities,
                gr.bundle_id,
                gr.stream,
                CASE WHEN gr.terminal_ingest_id <= :ingest_id THEN gr.terminal_event_id END AS visible_terminal_event_id,
                CASE WHEN gr.terminal_ingest_id <= :ingest_id THEN gr.finished_at END AS visible_finished_at,
                CASE WHEN gr.terminal_ingest_id <= :ingest_id THEN gr.outcome END AS visible_outcome,
                CASE WHEN gr.terminal_ingest_id <= :ingest_id THEN gr.expected_attempts END AS visible_expected_attempts,
                CASE WHEN gr.terminal_ingest_id <= :ingest_id THEN gr.latency_ms END AS visible_latency_ms,
                count(ue.event_id) FILTER (WHERE ue.attempt_index IS NOT NULL) AS visible_attempts,
                count(ue.event_id) FILTER (WHERE ue.attempt_index IS NULL) AS visible_denials,
                count(ue.event_id) FILTER (WHERE ue.attempt_index IS NOT NULL AND ue.token_usage_source = 'unavailable') AS unavailable_attempts,
                count(ue.event_id) FILTER (WHERE ue.attempt_index IS NOT NULL AND ue.token_usage_source = 'partial') AS partial_attempts,
                count(ue.event_id) FILTER (WHERE ue.attempt_index IS NOT NULL AND ue.token_usage_source = 'estimated') AS estimated_attempts,
                COALESCE(sum(ue.input_tokens) FILTER (WHERE ue.attempt_index IS NOT NULL), 0)::bigint AS known_input_tokens,
                COALESCE(sum(ue.output_tokens) FILTER (WHERE ue.attempt_index IS NOT NULL), 0)::bigint AS known_output_tokens,
                COALESCE(sum(ue.cost_usd) FILTER (WHERE ue.attempt_index IS NOT NULL), 0)::numeric(28, 12) AS known_cost_usd
            FROM gateway_request gr
            LEFT JOIN usage_event ue
                ON ue.org_id = gr.org_id
                AND ue.request_id = gr.request_id
                AND ue.ingest_id <= :ingest_id
            WHERE __FILTERS__
            GROUP BY gr.request_id
        ), facts AS (
            SELECT
                *,
                known_input_tokens + known_output_tokens AS known_tokens,
                CASE WHEN visible_latency_ms IS NULL THEN 1 ELSE 0 END AS latency_null_rank,
                __CONFIDENCE__ AS confidence
            FROM aggregated
        )
        SELECT * FROM facts
        __OUTER_WHERE__
        ORDER BY __ORDER__
        LIMIT :result_limit
        """
    statement = text(
        request_sql.replace("__FILTERS__", " AND ".join(clauses))
        .replace("__CONFIDENCE__", _confidence_sql())
        .replace("__OUTER_WHERE__", outer_where)
        .replace("__ORDER__", _order_sql(query))
    )
    return [dict(fact) for fact in (await current_session().execute(statement, parameters)).mappings()]


def _cursor_anchor(fact: dict[str, object], sort: RequestSort) -> RequestCursorAnchor:
    request_id = cast("UUID", fact["request_id"])
    started_at = cast("datetime", fact["request_started_at"])
    if str(sort) == "request_started_at":
        return RequestStartedAtAnchor(request_started_at=started_at, request_id=request_id)
    if str(sort) == "latency_ms":
        return RequestLatencyAnchor(
            null_rank=cast("Literal[0, 1]", fact["latency_null_rank"]),
            latency_ms=cast("int | None", fact["visible_latency_ms"]),
            request_started_at=started_at,
            request_id=request_id,
        )
    if str(sort) == "known_cost_usd":
        return RequestCostAnchor(
            known_cost_usd=cast("UsdAmount", fact["known_cost_usd"]),
            request_started_at=started_at,
            request_id=request_id,
        )
    return RequestTokensAnchor(
        known_tokens=cast("int", fact["known_tokens"]),
        request_started_at=started_at,
        request_id=request_id,
    )


async def _request_items(
    org_id: UUID,
    ingest_id: int,
    facts: list[dict[str, object]],
) -> list[GatewayRequestReportOut]:
    if not facts:
        return []
    request_ids = [fact["request_id"] for fact in facts]
    statement = text(
        """
        SELECT *
        FROM usage_event
        WHERE org_id = :org_id
            AND request_id = ANY(CAST(:request_ids AS uuid[]))
            AND ingest_id <= :ingest_id
        ORDER BY request_id, attempt_index NULLS LAST, occurred_at, event_id
        """
    )
    usage = (await current_session().execute(statement, {"org_id": org_id, "request_ids": request_ids, "ingest_id": ingest_id})).mappings()
    attempts: dict[UUID, list[ObservedRequestAttemptOut | UnavailableRequestAttemptOut]] = {cast("UUID", ident): [] for ident in request_ids}
    denials: dict[UUID, DeniedRequestEvidenceOut] = {}
    for usage_fact in usage:
        request_id = cast("UUID", usage_fact["request_id"])
        if usage_fact["attempt_index"] is None:
            denials[request_id] = DeniedRequestEvidenceOut.model_validate(dict(usage_fact))
            continue
        attempt_values = dict(usage_fact)
        attempt = (
            UnavailableRequestAttemptOut.model_validate(attempt_values)
            if usage_fact["token_usage_source"] == TokenUsageSource.UNAVAILABLE
            else ObservedRequestAttemptOut.model_validate(attempt_values)
        )
        attempts[request_id].append(attempt)
    results = []
    for fact in facts:
        request_id = cast("UUID", fact["request_id"])
        routed = attempts[request_id]
        expected_attempts = cast("int | None", fact.get("visible_expected_attempts"))
        accounting = build_request_accounting(
            expected_attempts,
            [
                RequestAttemptFact(
                    input_tokens=attempt.input_tokens,
                    output_tokens=attempt.output_tokens,
                    cache_read_tokens=attempt.cache_read_tokens,
                    cache_write_tokens=attempt.cache_write_tokens,
                    token_usage_source=attempt.token_usage_source,
                    cost_usd=attempt.cost_usd,
                )
                for attempt in routed
            ],
        )
        terminal = None
        if fact.get("visible_terminal_event_id") is not None:
            terminal = {
                "event_id": fact["visible_terminal_event_id"],
                "occurred_at": fact["visible_finished_at"],
                "outcome": fact["visible_outcome"],
                "expected_attempts": fact["visible_expected_attempts"],
                "latency_ms": fact["visible_latency_ms"],
            }
        results.append(
            GatewayRequestReportOut(
                request_id=request_id,
                request_started_at=cast("datetime", fact["request_started_at"]),
                org_id=cast("UUID", fact["org_id"]),
                workspace_id=cast("UUID", fact["workspace_id"]),
                workspace_label=cast("str", fact["workspace_label"]),
                key_id=cast("str", fact["key_id"]),
                authentication_source=cast("AuthenticationSource", fact["authentication_source"]),
                authentication_label=cast("str", fact["authentication_label"]),
                user_id=cast("UUID", fact["user_id"]),
                principal_label=cast("str", fact["principal_label"]),
                principal_type=cast("PrincipalType", fact["principal_type"]),
                requested_model_id=cast("str", fact["requested_model_id"]),
                requested_capabilities=cast("list[RequestCapability]", fact["requested_capabilities"]),
                bundle_id=cast("UUID", fact["bundle_id"]),
                stream=cast("bool", fact["stream"]),
                terminal=terminal,
                attempts=routed,
                denial=denials.get(request_id),
                **accounting.model_dump(),
            )
        )
    return results


def _export_row_limit() -> int:
    return request_report_module.MAX_EXPORT_ROWS
