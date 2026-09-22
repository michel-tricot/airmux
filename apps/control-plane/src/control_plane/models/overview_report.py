from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, cast
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, PlainSerializer, WithJsonSchema, field_validator, model_validator

from contract import CostSource, GatewayRequestOutcome, TokenUsageSource, UsdAmount
from contract.money import USD_AMOUNT_QUANTUM, fixed_point
from control_plane.models.common.wire import RequestModel


class OverviewRange(StrEnum):
    today = "today"
    seven_days = "7d"
    thirty_days = "30d"
    month_to_date = "month_to_date"
    custom = "custom"


class OverviewBucket(StrEnum):
    hour = "hour"
    day = "day"


class OverviewSplit(StrEnum):
    none = "none"
    workspace = "workspace"
    model = "model"
    provider = "provider"


class OverviewGroup(StrEnum):
    workspace = "workspace"
    principal = "principal"
    inference_key = "inference_key"
    model = "model"
    provider = "provider"


AccountingCompleteness = Literal["complete", "partial", "unavailable"]
DeliveryCompleteness = Literal["unavailable"]
KeyFilter = Annotated[str, Field(min_length=1, max_length=255)]
ModelFilter = Annotated[str, Field(min_length=1, max_length=255)]
ProviderFilter = Annotated[str, Field(min_length=1, max_length=63)]
SignedUsdAmount = Annotated[
    Decimal,
    Field(max_digits=29, decimal_places=12),
    PlainSerializer(fixed_point, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": r"^-?\d+(?:\.\d+)?$"}),
]
ExactRatio = Annotated[
    Decimal,
    Field(ge=0, le=1),
    PlainSerializer(fixed_point, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": r"^\d+(?:\.\d+)?$"}),
]
MAX_CUSTOM_DAYS = 366


class _OverviewReportQueryBase(RequestModel):
    range: OverviewRange = Field(description="Server-resolved report period preset")
    timezone: str = Field(min_length=1, max_length=100, description="IANA timezone used for calendar boundaries and buckets")
    start_date: date | None = Field(default=None, description="First included local calendar date for a custom range")
    end_date: date | None = Field(default=None, description="Last included local calendar date for a custom range")
    bucket: OverviewBucket = Field(default=OverviewBucket.day, description="Current-period series bucket size")
    split: OverviewSplit = Field(
        default=OverviewSplit.none,
        description="Optional series split; model/provider request counts are assigned to the final included routed attempt",
    )
    group: OverviewGroup = Field(
        default=OverviewGroup.workspace,
        description="Attribution grouping; model/provider request counts are assigned to the final included routed attempt",
    )
    principal: list[UUID] = Field(default_factory=list, max_length=50, description="Repeated principal/user snapshot ID filter")
    inference_key: list[KeyFilter] = Field(default_factory=list, max_length=50, description="Repeated inference key snapshot ID filter")
    model: list[ModelFilter] = Field(
        default_factory=list,
        max_length=50,
        description="Repeated routed-model filter; values are ORed, while model and provider filters must match the same visible attempt",
    )
    provider: list[ProviderFilter] = Field(
        default_factory=list,
        max_length=50,
        description="Repeated routed-provider filter; values are ORed, while model and provider filters must match the same visible attempt",
    )
    as_of: UUID | None = Field(default=None, description="Opaque committed ingestion watermark; omit for the latest committed batch")

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            message = "timezone must be a valid IANA timezone"
            raise ValueError(message) from exc
        return value

    @model_validator(mode="after")
    def valid_dates(self) -> _OverviewReportQueryBase:
        if self.range is OverviewRange.custom:
            if self.start_date is None or self.end_date is None:
                message = "start_date and end_date are required for custom range"
                raise ValueError(message)
            if self.start_date > self.end_date:
                message = "start_date must be on or before end_date"
                raise ValueError(message)
            if (self.end_date - self.start_date).days >= MAX_CUSTOM_DAYS:
                message = "custom range must not exceed 366 inclusive days"
                raise ValueError(message)
        elif self.start_date is not None or self.end_date is not None:
            message = "start_date and end_date are only accepted for custom range"
            raise ValueError(message)
        return self


class OverviewReportQuery(_OverviewReportQueryBase):
    workspace: list[UUID] = Field(default_factory=list, max_length=50, description="Repeated workspace snapshot ID filter")


class WorkspaceOverviewReportQuery(_OverviewReportQueryBase):
    pass


class OverviewPeriodOut(BaseModel):
    start_at: datetime
    end_at: datetime
    timezone: str


class OverviewPeriodsOut(BaseModel):
    current: OverviewPeriodOut
    comparison: OverviewPeriodOut


class OverviewFreshnessOut(BaseModel):
    watermark: UUID | None
    received_at: datetime
    delivery_completeness: DeliveryCompleteness = "unavailable"


class OutcomeCountsOut(BaseModel):
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    denied: int = Field(ge=0)
    timeout: int = Field(ge=0)
    cancelled: int = Field(ge=0)


class TokenSourceCountsOut(BaseModel):
    provider: int = Field(ge=0)
    estimated: int = Field(ge=0)
    partial: int = Field(ge=0)
    unavailable: int = Field(ge=0)
    not_applicable: int = Field(ge=0)


class CostSourceCountsOut(BaseModel):
    catalog_estimate: int = Field(ge=0)
    unavailable: int = Field(ge=0)
    not_applicable: int = Field(ge=0)


class OverviewMetricsOut(BaseModel):
    logical_requests: int = Field(
        ge=0,
        description="Distinct logical requests; model and provider splits assign each request to its final included routed attempt",
    )
    attempts: int = Field(ge=0)
    outcomes: OutcomeCountsOut
    pending_requests: int = Field(ge=0)
    incomplete_requests: int = Field(ge=0)
    known_input_tokens: int = Field(ge=0)
    known_output_tokens: int = Field(ge=0)
    known_cache_read_tokens: int = Field(ge=0)
    known_cache_write_tokens: int = Field(ge=0)
    unavailable_usage_attempts: int = Field(ge=0)
    token_sources: TokenSourceCountsOut = Field(description="Stored token provenance counts for routed attempts and denial observations")
    known_cost_usd: UsdAmount
    unpriced_attempts: int = Field(ge=0)
    cost_sources: CostSourceCountsOut = Field(description="Stored pricing provenance counts for routed attempts and denial observations")
    cost_per_request_usd: UsdAmount | None
    cost_per_request_denominator: int = Field(ge=0)
    token_completeness: AccountingCompleteness
    cost_completeness: AccountingCompleteness


class OutcomeCountsDeltaOut(BaseModel):
    succeeded: int
    failed: int
    denied: int
    timeout: int
    cancelled: int


class TokenSourceCountsDeltaOut(BaseModel):
    provider: int
    estimated: int
    partial: int
    unavailable: int
    not_applicable: int


class CostSourceCountsDeltaOut(BaseModel):
    catalog_estimate: int
    unavailable: int
    not_applicable: int


class OverviewMetricsDeltaOut(BaseModel):
    logical_requests: int
    attempts: int
    outcomes: OutcomeCountsDeltaOut
    pending_requests: int
    incomplete_requests: int
    known_input_tokens: int
    known_output_tokens: int
    known_cache_read_tokens: int
    known_cache_write_tokens: int
    unavailable_usage_attempts: int
    token_sources: TokenSourceCountsDeltaOut
    known_cost_usd: SignedUsdAmount
    unpriced_attempts: int
    cost_sources: CostSourceCountsDeltaOut
    cost_per_request_usd: SignedUsdAmount | None


class OverviewSummaryOut(BaseModel):
    current: OverviewMetricsOut
    comparison: OverviewMetricsOut
    delta: OverviewMetricsDeltaOut


class OverviewSeriesPointOut(BaseModel):
    start_at: datetime
    end_at: datetime
    split_id: str | None
    split_label: str
    metrics: OverviewMetricsOut


class OverviewAttributionOut(BaseModel):
    id: str | None
    label: str
    known_cost_usd: UsdAmount
    share_of_known_cost: ExactRatio | None
    logical_requests: int = Field(ge=0)
    attempts: int = Field(ge=0)
    incomplete_requests: int = Field(ge=0)
    unavailable_usage_attempts: int = Field(ge=0)
    token_sources: TokenSourceCountsOut
    unpriced_attempts: int = Field(ge=0)
    cost_sources: CostSourceCountsOut
    token_completeness: AccountingCompleteness
    cost_completeness: AccountingCompleteness


class OverviewReportOut(BaseModel):
    freshness: OverviewFreshnessOut
    periods: OverviewPeriodsOut
    bucket: OverviewBucket
    split: OverviewSplit
    group: OverviewGroup
    summary: OverviewSummaryOut
    series: list[OverviewSeriesPointOut]
    attribution: list[OverviewAttributionOut]


class UnknownReportWatermarkError(ValueError):
    def __init__(self) -> None:
        super().__init__("Unknown report watermark")


class ReportFact(BaseModel):
    request_id: UUID
    request_started_at: datetime
    workspace_id: UUID
    workspace_label: str
    key_id: str
    authentication_label: str
    user_id: UUID
    principal_label: str
    outcome: GatewayRequestOutcome | None
    expected_attempts: int | None
    visible_attempts: int = Field(ge=0)
    attempt_index: int | None
    model_id: str | None
    provider_id: str | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    token_usage_source: TokenUsageSource | None
    cost_source: CostSource | None
    cost_usd: UsdAmount | None


def resolve_periods(query: _OverviewReportQueryBase, anchor: datetime) -> OverviewPeriodsOut:
    timezone = ZoneInfo(query.timezone)
    local_anchor = anchor.astimezone(timezone)
    if query.range is OverviewRange.custom:
        start_date = cast("date", query.start_date)
        end_date = cast("date", query.end_date)
        current_start = datetime.combine(start_date, time.min, timezone).astimezone(UTC)
        current_end = datetime.combine(end_date + timedelta(days=1), time.min, timezone).astimezone(UTC)
    else:
        days = 6 if query.range is OverviewRange.seven_days else 29 if query.range is OverviewRange.thirty_days else 0
        start_date = local_anchor.date() - timedelta(days=days)
        if query.range is OverviewRange.month_to_date:
            start_date = local_anchor.date().replace(day=1)
        current_start = datetime.combine(start_date, time.min, timezone).astimezone(UTC)
        current_end = anchor.astimezone(UTC)
    comparison_end = current_start
    comparison_start = comparison_end - (current_end - current_start)
    return OverviewPeriodsOut(
        current=OverviewPeriodOut(start_at=current_start, end_at=current_end, timezone=query.timezone),
        comparison=OverviewPeriodOut(start_at=comparison_start, end_at=comparison_end, timezone=query.timezone),
    )


def build_overview_report(
    query: _OverviewReportQueryBase,
    freshness: OverviewFreshnessOut,
    periods: OverviewPeriodsOut,
    facts: list[ReportFact],
) -> OverviewReportOut:
    requests = _requests(facts)
    current_requests = _in_period(requests, periods.current)
    comparison_requests = _in_period(requests, periods.comparison)
    current = _metrics(current_requests)
    comparison = _metrics(comparison_requests)
    return OverviewReportOut(
        freshness=freshness,
        periods=periods,
        bucket=query.bucket,
        split=query.split,
        group=query.group,
        summary=OverviewSummaryOut(current=current, comparison=comparison, delta=_delta(current, comparison)),
        series=_series(query, periods.current, current_requests),
        attribution=_attribution(query.group, current_requests),
    )


def _requests(facts: list[ReportFact]) -> list[list[ReportFact]]:
    grouped: dict[UUID, list[ReportFact]] = defaultdict(list)
    for fact in facts:
        grouped[fact.request_id].append(fact)
    return list(grouped.values())


def _in_period(requests: list[list[ReportFact]], period: OverviewPeriodOut) -> list[list[ReportFact]]:
    return [request for request in requests if period.start_at <= request[0].request_started_at < period.end_at]


def _attempts(request: list[ReportFact]) -> list[ReportFact]:
    return [fact for fact in request if fact.attempt_index is not None]


def _metrics(requests: list[list[ReportFact]], counted_request_ids: set[UUID] | None = None) -> OverviewMetricsOut:
    attempts = [attempt for request in requests for attempt in _attempts(request)]
    observations = [fact for request in requests for fact in request if fact.token_usage_source is not None]
    counted_requests = requests if counted_request_ids is None else [request for request in requests if request[0].request_id in counted_request_ids]
    outcomes = Counter(request[0].outcome for request in counted_requests)
    incomplete = sum(request[0].outcome is None or request[0].visible_attempts != request[0].expected_attempts for request in counted_requests)
    unavailable_usage = sum(attempt.token_usage_source is TokenUsageSource.UNAVAILABLE for attempt in attempts)
    unpriced = sum(attempt.cost_usd is None for attempt in attempts)
    token_sources = Counter(fact.token_usage_source for fact in observations)
    cost_sources = Counter(fact.cost_source for fact in observations)
    known_cost = sum((attempt.cost_usd for attempt in attempts if attempt.cost_usd is not None), start=Decimal(0))
    logical_requests = len(counted_requests)
    return OverviewMetricsOut(
        logical_requests=logical_requests,
        attempts=len(attempts),
        outcomes=OutcomeCountsOut(
            succeeded=outcomes["succeeded"],
            failed=outcomes["failed"],
            denied=outcomes["denied"],
            timeout=outcomes["timeout"],
            cancelled=outcomes["cancelled"],
        ),
        pending_requests=outcomes[None],
        incomplete_requests=incomplete,
        known_input_tokens=sum(attempt.input_tokens or 0 for attempt in attempts),
        known_output_tokens=sum(attempt.output_tokens or 0 for attempt in attempts),
        known_cache_read_tokens=sum(attempt.cache_read_tokens or 0 for attempt in attempts),
        known_cache_write_tokens=sum(attempt.cache_write_tokens or 0 for attempt in attempts),
        unavailable_usage_attempts=unavailable_usage,
        token_sources=TokenSourceCountsOut(
            provider=token_sources[TokenUsageSource.PROVIDER],
            estimated=token_sources[TokenUsageSource.ESTIMATED],
            partial=token_sources[TokenUsageSource.PARTIAL],
            unavailable=token_sources[TokenUsageSource.UNAVAILABLE],
            not_applicable=token_sources[TokenUsageSource.NOT_APPLICABLE],
        ),
        known_cost_usd=known_cost,
        unpriced_attempts=unpriced,
        cost_sources=CostSourceCountsOut(
            catalog_estimate=cost_sources["catalog_estimate"],
            unavailable=cost_sources["unavailable"],
            not_applicable=cost_sources["not_applicable"],
        ),
        cost_per_request_usd=(known_cost / logical_requests).quantize(USD_AMOUNT_QUANTUM) if logical_requests else None,
        cost_per_request_denominator=logical_requests,
        token_completeness=_completeness(len(attempts), unavailable_usage, incomplete),
        cost_completeness=_completeness(len(attempts), unpriced, incomplete),
    )


def _completeness(total: int, unknown: int, incomplete: int) -> AccountingCompleteness:
    if total == 0 and incomplete > 0:
        return "unavailable"
    if total > 0 and unknown == total:
        return "unavailable"
    if unknown > 0 or incomplete > 0:
        return "partial"
    return "complete"


def _delta(current: OverviewMetricsOut, comparison: OverviewMetricsOut) -> OverviewMetricsDeltaOut:
    cost_per_request = (
        current.cost_per_request_usd - comparison.cost_per_request_usd
        if current.cost_per_request_usd is not None and comparison.cost_per_request_usd is not None
        else None
    )
    return OverviewMetricsDeltaOut(
        logical_requests=current.logical_requests - comparison.logical_requests,
        attempts=current.attempts - comparison.attempts,
        outcomes=OutcomeCountsDeltaOut(
            succeeded=current.outcomes.succeeded - comparison.outcomes.succeeded,
            failed=current.outcomes.failed - comparison.outcomes.failed,
            denied=current.outcomes.denied - comparison.outcomes.denied,
            timeout=current.outcomes.timeout - comparison.outcomes.timeout,
            cancelled=current.outcomes.cancelled - comparison.outcomes.cancelled,
        ),
        pending_requests=current.pending_requests - comparison.pending_requests,
        incomplete_requests=current.incomplete_requests - comparison.incomplete_requests,
        known_input_tokens=current.known_input_tokens - comparison.known_input_tokens,
        known_output_tokens=current.known_output_tokens - comparison.known_output_tokens,
        known_cache_read_tokens=current.known_cache_read_tokens - comparison.known_cache_read_tokens,
        known_cache_write_tokens=current.known_cache_write_tokens - comparison.known_cache_write_tokens,
        unavailable_usage_attempts=current.unavailable_usage_attempts - comparison.unavailable_usage_attempts,
        token_sources=TokenSourceCountsDeltaOut(
            provider=current.token_sources.provider - comparison.token_sources.provider,
            estimated=current.token_sources.estimated - comparison.token_sources.estimated,
            partial=current.token_sources.partial - comparison.token_sources.partial,
            unavailable=current.token_sources.unavailable - comparison.token_sources.unavailable,
            not_applicable=current.token_sources.not_applicable - comparison.token_sources.not_applicable,
        ),
        known_cost_usd=current.known_cost_usd - comparison.known_cost_usd,
        unpriced_attempts=current.unpriced_attempts - comparison.unpriced_attempts,
        cost_sources=CostSourceCountsDeltaOut(
            catalog_estimate=current.cost_sources.catalog_estimate - comparison.cost_sources.catalog_estimate,
            unavailable=current.cost_sources.unavailable - comparison.cost_sources.unavailable,
            not_applicable=current.cost_sources.not_applicable - comparison.cost_sources.not_applicable,
        ),
        cost_per_request_usd=cost_per_request,
    )


def _series(
    query: _OverviewReportQueryBase,
    period: OverviewPeriodOut,
    requests: list[list[ReportFact]],
) -> list[OverviewSeriesPointOut]:
    groups: dict[tuple[datetime, str | None, str], dict[UUID, list[ReportFact]]] = defaultdict(lambda: defaultdict(list))
    counted: dict[tuple[datetime, str | None, str], set[UUID]] = defaultdict(set)
    for request in requests:
        bucket_start, _ = _bucket(request[0].request_started_at, query.bucket, query.timezone, period.end_at)
        for split_id, split_label, split_request, counts_request in _partition(request, query.split):
            key = (bucket_start, split_id, split_label)
            groups[key][request[0].request_id].extend(split_request)
            if counts_request:
                counted[key].add(request[0].request_id)
    return [
        OverviewSeriesPointOut(
            start_at=start_at,
            end_at=_bucket_end(start_at, query.bucket, query.timezone, period.end_at),
            split_id=split_id,
            split_label=split_label,
            metrics=_metrics(list(grouped.values()), counted[(start_at, split_id, split_label)]),
        )
        for (start_at, split_id, split_label), grouped in sorted(groups.items(), key=lambda item: (item[0][0], item[0][2]))
    ]


def _bucket(started_at: datetime, bucket: OverviewBucket, timezone_name: str, period_end: datetime) -> tuple[datetime, datetime]:
    timezone = ZoneInfo(timezone_name)
    local = started_at.astimezone(timezone)
    if bucket is OverviewBucket.hour:
        start_at = local.replace(minute=0, second=0, microsecond=0).astimezone(UTC)
    else:
        start_at = datetime.combine(local.date(), time.min, timezone).astimezone(UTC)
    return start_at, _bucket_end(start_at, bucket, timezone_name, period_end)


def _bucket_end(start_at: datetime, bucket: OverviewBucket, timezone_name: str, period_end: datetime) -> datetime:
    if bucket is OverviewBucket.hour:
        return min(start_at + timedelta(hours=1), period_end)
    timezone = ZoneInfo(timezone_name)
    next_date = start_at.astimezone(timezone).date() + timedelta(days=1)
    return min(datetime.combine(next_date, time.min, timezone).astimezone(UTC), period_end)


def _partition(request: list[ReportFact], split: OverviewSplit) -> list[tuple[str | None, str, list[ReportFact], bool]]:
    first = request[0]
    if split is OverviewSplit.none:
        return [(None, "All", request, True)]
    if split is OverviewSplit.workspace:
        return [(str(first.workspace_id), first.workspace_label, request, True)]
    attempts = _attempts(request)
    if not attempts:
        return [(None, "Unattributed", request, True)]
    grouped: dict[str, list[ReportFact]] = defaultdict(list)
    for attempt in attempts:
        value = attempt.model_id if split is OverviewSplit.model else attempt.provider_id
        if value is not None:
            grouped[value].append(attempt)
    final_attempt = max(attempts, key=lambda attempt: attempt.attempt_index or 0)
    final_value = (final_attempt.model_id if split is OverviewSplit.model else final_attempt.provider_id) or ""
    grouped[final_value].extend(fact for fact in request if fact.attempt_index is None and fact.token_usage_source is not None)
    return [(value or None, value or "Unattributed", facts, value == final_value) for value, facts in grouped.items()]


def _attribution(group: OverviewGroup, requests: list[list[ReportFact]]) -> list[OverviewAttributionOut]:
    grouped: dict[tuple[str | None, str], dict[UUID, list[ReportFact]]] = defaultdict(lambda: defaultdict(list))
    counted: dict[tuple[str | None, str], set[UUID]] = defaultdict(set)
    for request in requests:
        for group_id, label, group_request, counts_request in _group(request, group):
            key = (group_id, label)
            grouped[key][request[0].request_id].extend(group_request)
            if counts_request:
                counted[key].add(request[0].request_id)
    known_total = _metrics(requests).known_cost_usd
    attribution = []
    for (group_id, label), grouped_requests in grouped.items():
        metrics = _metrics(list(grouped_requests.values()), counted[(group_id, label)])
        attribution.append(
            OverviewAttributionOut(
                id=group_id,
                label=label,
                known_cost_usd=metrics.known_cost_usd,
                share_of_known_cost=metrics.known_cost_usd / known_total if known_total else None,
                logical_requests=metrics.logical_requests,
                attempts=metrics.attempts,
                incomplete_requests=metrics.incomplete_requests,
                unavailable_usage_attempts=metrics.unavailable_usage_attempts,
                token_sources=metrics.token_sources,
                unpriced_attempts=metrics.unpriced_attempts,
                cost_sources=metrics.cost_sources,
                token_completeness=metrics.token_completeness,
                cost_completeness=metrics.cost_completeness,
            )
        )
    return sorted(attribution, key=lambda item: (-item.known_cost_usd, item.label, item.id or ""))


def _group(request: list[ReportFact], group: OverviewGroup) -> list[tuple[str | None, str, list[ReportFact], bool]]:
    first = request[0]
    if group is OverviewGroup.workspace:
        return [(str(first.workspace_id), first.workspace_label, request, True)]
    if group is OverviewGroup.principal:
        return [(str(first.user_id), first.principal_label, request, True)]
    if group is OverviewGroup.inference_key:
        return [(first.key_id, first.authentication_label, request, True)]
    split = OverviewSplit.model if group is OverviewGroup.model else OverviewSplit.provider
    return _partition(request, split)
