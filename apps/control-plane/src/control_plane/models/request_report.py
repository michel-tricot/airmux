from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import io
import json
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from contract import (
    AuthenticationSource,
    CredentialScope,
    GatewayRequestOutcome,
    PrincipalType,
    TokenUsageSource,
    UsdAmount,
    UsdRate,
)
from contract.events import RoutedUsageStatus
from contract.model_types import RequestCapability
from control_plane.models.common import InvalidCursorError
from control_plane.models.common.wire import PageInfo, RequestModel
from control_plane.models.overview_report import (
    AccountingCompleteness,
    KeyFilter,
    ModelFilter,
    OverviewFreshnessOut,
    OverviewPeriodOut,
    ProviderFilter,
    ReportAsOfToken,
    ReportSnapshotV1,
    _ReportPeriodQueryBase,
    decode_report_snapshot,
    encode_report_snapshot,
)

MAX_EXPORT_ROWS = 100_000
MAX_EXPORT_EVIDENCE = 500_000
MAX_EXPORT_BYTES = 32 * 1024 * 1024
MAX_CURSOR_LENGTH = 512
_CURSOR_CHARACTERS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")

RequestOutcome = Literal["pending", "succeeded", "failed", "denied", "timeout", "cancelled"]
RequestConfidence = Literal["provider", "estimated", "partial", "unavailable", "not_applicable"]
ProviderCredentialFilter = UUID | Literal["unattributed"]
RequestCursorToken = Annotated[str, StringConstraints(min_length=1, max_length=MAX_CURSOR_LENGTH, pattern=r"^[A-Za-z0-9_-]+$")]


class RequestSort(StrEnum):
    request_started_at = "request_started_at"
    latency_ms = "latency_ms"
    known_cost_usd = "known_cost_usd"
    known_tokens = "known_tokens"


class SortDirection(StrEnum):
    asc = "asc"
    desc = "desc"


class _RequestFilterQuery(_ReportPeriodQueryBase):
    principal: list[UUID] = Field(default_factory=list, max_length=50, description="Repeated principal snapshot ID filter")
    inference_key: list[KeyFilter] = Field(default_factory=list, max_length=50, description="Repeated inference key snapshot ID filter")
    model: list[ModelFilter] = Field(default_factory=list, max_length=50, description="Repeated routed-model request selector")
    provider: list[ProviderFilter] = Field(default_factory=list, max_length=50, description="Repeated routed-provider request selector")
    provider_credential: list[ProviderCredentialFilter] = Field(
        default_factory=list,
        max_length=50,
        description="Repeated immutable provider credential snapshot UUID or unattributed request selector",
    )
    outcome: list[RequestOutcome] = Field(default_factory=list, max_length=50, description="Repeated terminal outcome or pending filter")
    confidence: list[RequestConfidence] = Field(default_factory=list, max_length=50, description="Repeated request accounting confidence filter")
    search: str | None = Field(default=None, max_length=320, description="Literal search across immutable request and attempt snapshots")
    sort: RequestSort = RequestSort.request_started_at
    direction: SortDirection = SortDirection.desc
    as_of: ReportAsOfToken | None = Field(default=None, description="Opaque report snapshot; omit for the latest relevant committed evidence")

    @field_validator("search", mode="before")
    @classmethod
    def trimmed_search(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        search = value.strip()
        if not search:
            message = "search must not be blank"
            raise ValueError(message)
        return search

    @field_validator("inference_key", "model", "provider", mode="before")
    @classmethod
    def trimmed_string_filters(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        normalized = [item.strip() if isinstance(item, str) else item for item in value]
        if any(item == "" for item in normalized):
            message = "filter values must not be blank"
            raise ValueError(message)
        return normalized


class OrgRequestExportQuery(_RequestFilterQuery):
    workspace: list[UUID] = Field(default_factory=list, max_length=50, description="Repeated workspace snapshot ID filter")


class WorkspaceRequestExportQuery(_RequestFilterQuery):
    pass


class OrgRequestReportQuery(OrgRequestExportQuery):
    cursor: RequestCursorToken | None = None
    limit: int = Field(default=50, ge=1, le=200)


class WorkspaceRequestReportQuery(WorkspaceRequestExportQuery):
    cursor: RequestCursorToken | None = None
    limit: int = Field(default=50, ge=1, le=200)


class RequestAsOfQuery(RequestModel):
    as_of: ReportAsOfToken | None = Field(default=None, description="Opaque report snapshot; omit for the latest relevant committed evidence")


class RequestStartedAtAnchor(BaseModel):
    kind: Literal["request_started_at"] = "request_started_at"
    request_started_at: AwareDatetime
    request_id: UUID


class RequestLatencyAnchor(BaseModel):
    kind: Literal["latency_ms"] = "latency_ms"
    null_rank: Literal[0, 1]
    latency_ms: int | None = Field(ge=0)
    request_started_at: AwareDatetime
    request_id: UUID

    @model_validator(mode="after")
    def valid_null_rank(self) -> Self:
        if (self.null_rank == 1) != (self.latency_ms is None):
            message = "latency null rank must match latency_ms"
            raise ValueError(message)
        return self


class RequestCostAnchor(BaseModel):
    kind: Literal["known_cost_usd"] = "known_cost_usd"
    known_cost_usd: UsdAmount
    request_started_at: AwareDatetime
    request_id: UUID


class RequestTokensAnchor(BaseModel):
    kind: Literal["known_tokens"] = "known_tokens"
    known_tokens: int = Field(ge=0)
    request_started_at: AwareDatetime
    request_id: UUID


RequestCursorAnchor = Annotated[
    RequestStartedAtAnchor | RequestLatencyAnchor | RequestCostAnchor | RequestTokensAnchor,
    Field(discriminator="kind"),
]


class RequestCursorV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    as_of: ReportAsOfToken
    sort: RequestSort
    direction: SortDirection
    anchor: RequestCursorAnchor
    fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def matching_anchor(self) -> Self:
        if self.anchor.kind != self.sort.value:
            message = "cursor anchor must match sort"
            raise ValueError(message)
        return self


def encode_request_cursor(cursor: RequestCursorV1) -> RequestCursorToken:
    sort_code = {
        RequestSort.request_started_at: "r",
        RequestSort.latency_ms: "l",
        RequestSort.known_cost_usd: "c",
        RequestSort.known_tokens: "t",
    }[cursor.sort]
    anchor = cursor.anchor
    anchor_values: list[object]
    if isinstance(anchor, RequestStartedAtAnchor):
        anchor_values = [anchor.request_started_at.isoformat(), str(anchor.request_id)]
    elif isinstance(anchor, RequestLatencyAnchor):
        anchor_values = [anchor.null_rank, anchor.latency_ms, anchor.request_started_at.isoformat(), str(anchor.request_id)]
    elif isinstance(anchor, RequestCostAnchor):
        anchor_values = [format(anchor.known_cost_usd, "f"), anchor.request_started_at.isoformat(), str(anchor.request_id)]
    else:
        anchor_values = [anchor.known_tokens, anchor.request_started_at.isoformat(), str(anchor.request_id)]
    snapshot = decode_report_snapshot(cursor.as_of)
    payload = {
        "a": anchor_values,
        "d": "a" if cursor.direction is SortDirection.asc else "d",
        "f": base64.urlsafe_b64encode(bytes.fromhex(cursor.fingerprint)).decode().rstrip("="),
        "s": sort_code,
        "v": 1,
        "w": [
            str(snapshot.watermark) if snapshot.watermark is not None else None,
            snapshot.resolved_at.isoformat(),
            str(snapshot.org_id),
            str(snapshot.workspace_id) if snapshot.workspace_id is not None else None,
        ],
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    token = base64.urlsafe_b64encode(encoded).decode().rstrip("=")
    if len(token) > MAX_CURSOR_LENGTH:
        raise InvalidCursorError
    return token


def _decoded_request_cursor(token: str) -> RequestCursorV1:
    if len(token) > MAX_CURSOR_LENGTH or not token or any(character not in _CURSOR_CHARACTERS for character in token):
        raise ValueError
    raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
    payload = json.loads(raw)
    if not isinstance(payload, dict) or set(payload) != {"a", "d", "f", "s", "v", "w"}:
        raise ValueError
    sort = {"r": RequestSort.request_started_at, "l": RequestSort.latency_ms, "c": RequestSort.known_cost_usd, "t": RequestSort.known_tokens}[
        payload["s"]
    ]
    values = payload["a"]
    match sort, values:
        case RequestSort.request_started_at, [started_at, request_id]:
            anchor: RequestCursorAnchor = RequestStartedAtAnchor(request_started_at=started_at, request_id=request_id)
        case RequestSort.latency_ms, [null_rank, latency_ms, started_at, request_id]:
            anchor = RequestLatencyAnchor(
                null_rank=null_rank,
                latency_ms=latency_ms,
                request_started_at=started_at,
                request_id=request_id,
            )
        case RequestSort.known_cost_usd, [known_cost_usd, started_at, request_id]:
            anchor = RequestCostAnchor(known_cost_usd=known_cost_usd, request_started_at=started_at, request_id=request_id)
        case RequestSort.known_tokens, [known_tokens, started_at, request_id]:
            anchor = RequestTokensAnchor(known_tokens=known_tokens, request_started_at=started_at, request_id=request_id)
        case _:
            raise ValueError
    cursor = RequestCursorV1(
        version=payload["v"],
        as_of=encode_report_snapshot(
            ReportSnapshotV1(
                watermark=payload["w"][0],
                resolved_at=payload["w"][1],
                org_id=payload["w"][2],
                workspace_id=payload["w"][3],
            )
        ),
        sort=sort,
        direction={"a": SortDirection.asc, "d": SortDirection.desc}[payload["d"]],
        anchor=anchor,
        fingerprint=base64.b64decode(payload["f"] + "=" * (-len(payload["f"]) % 4), altchars=b"-_", validate=True).hex(),
    )
    if encode_request_cursor(cursor) != token:
        raise ValueError
    return cursor


def decode_request_cursor(token: str) -> RequestCursorV1:
    try:
        cursor = _decoded_request_cursor(token)
    except (IndexError, KeyError, TypeError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError, ValueError, OverflowError) as error:
        raise InvalidCursorError from error
    else:
        return cursor


def request_query_fingerprint(
    query: _RequestFilterQuery,
    org_id: UUID,
    workspace_id: UUID | None,
    period: OverviewPeriodOut,
) -> str:
    values = query.model_dump(mode="json", exclude={"as_of", "cursor", "limit"})
    for field in ("workspace", "principal", "inference_key", "model", "provider", "provider_credential", "outcome", "confidence"):
        if field in values:
            values[field] = sorted(set(values[field]))
    values["org_id"] = str(org_id)
    values["workspace_scope"] = str(workspace_id) if workspace_id is not None else None
    values["period_start"] = period.start_at.isoformat()
    values["period_end"] = period.end_at.isoformat()
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_request_cursor(
    cursor: RequestCursorV1,
    query: _RequestFilterQuery,
    org_id: UUID,
    workspace_id: UUID | None,
    period: OverviewPeriodOut,
) -> None:
    if query.as_of is not None and query.as_of != cursor.as_of:
        raise InvalidCursorError
    if cursor.sort is not query.sort or cursor.direction is not query.direction:
        raise InvalidCursorError
    if cursor.fingerprint != request_query_fingerprint(query, org_id, workspace_id, period):
        raise InvalidCursorError


class RequestTerminalOut(BaseModel):
    event_id: UUID
    occurred_at: datetime
    outcome: GatewayRequestOutcome
    expected_attempts: int = Field(ge=0)
    latency_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def successful_request_was_routed(self) -> Self:
        if self.outcome == "succeeded" and self.expected_attempts == 0:
            message = "a succeeded request requires at least one routed attempt"
            raise ValueError(message)
        return self


class _RoutedRequestAttemptOut(BaseModel):
    event_id: UUID
    attempt_index: int = Field(ge=1)
    attempt_started_at: datetime
    occurred_at: datetime
    model_id: str
    provider_id: str
    max_output_tokens: int | None = Field(ge=1)
    input_price_per_mtok: UsdRate
    output_price_per_mtok: UsdRate
    cache_read_price_per_mtok: UsdRate
    cache_write_price_per_mtok: UsdRate
    latency_ms: int = Field(ge=0)
    status: RoutedUsageStatus
    credential_id: UUID
    credential_scope: CredentialScope
    credential_name: str


class ObservedRequestAttemptOut(_RoutedRequestAttemptOut):
    token_usage_source: Literal[
        TokenUsageSource.PROVIDER,
        TokenUsageSource.ESTIMATED,
        TokenUsageSource.PARTIAL,
    ]
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cache_read_tokens: int = Field(ge=0)
    cache_write_tokens: int = Field(ge=0)
    cost_source: Literal["catalog_estimate"]
    cost_usd: UsdAmount
    cost_input_usd: UsdAmount
    cost_output_usd: UsdAmount

    @model_validator(mode="after")
    def exact_observation(self) -> Self:
        if self.input_tokens < self.cache_read_tokens + self.cache_write_tokens:
            message = "input tokens must include cache-read and cache-write tokens"
            raise ValueError(message)
        if self.cost_usd != self.cost_input_usd + self.cost_output_usd:
            message = "cost_usd must equal cost_input_usd plus cost_output_usd"
            raise ValueError(message)
        return self


class UnavailableRequestAttemptOut(_RoutedRequestAttemptOut):
    token_usage_source: Literal[TokenUsageSource.UNAVAILABLE]
    input_tokens: None
    output_tokens: None
    cache_read_tokens: None
    cache_write_tokens: None
    cost_source: Literal["unavailable"]
    cost_usd: None
    cost_input_usd: None
    cost_output_usd: None


RequestAttemptOut = Annotated[
    ObservedRequestAttemptOut | UnavailableRequestAttemptOut,
    Field(discriminator="token_usage_source"),
]


class DeniedRequestEvidenceOut(BaseModel):
    event_id: UUID
    occurred_at: datetime
    input_tokens: Literal[0]
    output_tokens: Literal[0]
    cache_read_tokens: Literal[0]
    cache_write_tokens: Literal[0]
    token_usage_source: Literal[TokenUsageSource.NOT_APPLICABLE]
    cost_source: Literal["not_applicable"]
    cost_usd: UsdAmount
    cost_input_usd: UsdAmount
    cost_output_usd: UsdAmount
    latency_ms: int = Field(ge=0)
    status: Literal["denied"]

    @model_validator(mode="after")
    def zero_cost(self) -> Self:
        if any(value != Decimal(0) for value in (self.cost_usd, self.cost_input_usd, self.cost_output_usd)):
            message = "denial evidence must have zero cost"
            raise ValueError(message)
        return self


class RequestAttemptFact(BaseModel):
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    token_usage_source: TokenUsageSource
    cost_usd: UsdAmount | None


class RequestAccountingOut(BaseModel):
    evidence_complete: bool
    confidence: RequestConfidence
    known_input_tokens: int = Field(ge=0)
    known_output_tokens: int = Field(ge=0)
    known_cache_read_tokens: int = Field(ge=0)
    known_cache_write_tokens: int = Field(ge=0)
    known_cost_usd: UsdAmount
    token_completeness: AccountingCompleteness
    cost_completeness: AccountingCompleteness


def build_request_accounting(
    expected_attempts: int | None,
    attempts: list[RequestAttemptFact],
) -> RequestAccountingOut:
    visible = len(attempts)
    incomplete = expected_attempts is None or visible != expected_attempts
    unavailable = sum(attempt.token_usage_source is TokenUsageSource.UNAVAILABLE for attempt in attempts)
    if expected_attempts == 0 and visible == 0:
        confidence: RequestConfidence = "not_applicable"
    elif visible == 0 or unavailable:
        confidence = "unavailable"
    elif incomplete or any(attempt.token_usage_source is TokenUsageSource.PARTIAL for attempt in attempts):
        confidence = "partial"
    elif any(attempt.token_usage_source is TokenUsageSource.ESTIMATED for attempt in attempts):
        confidence = "estimated"
    else:
        confidence = "provider"
    completeness: AccountingCompleteness
    if (visible == 0 and incomplete) or (visible > 0 and unavailable == visible):
        completeness = "unavailable"
    elif unavailable or incomplete:
        completeness = "partial"
    else:
        completeness = "complete"
    return RequestAccountingOut(
        evidence_complete=not incomplete,
        confidence=confidence,
        known_input_tokens=sum(attempt.input_tokens or 0 for attempt in attempts),
        known_output_tokens=sum(attempt.output_tokens or 0 for attempt in attempts),
        known_cache_read_tokens=sum(attempt.cache_read_tokens or 0 for attempt in attempts),
        known_cache_write_tokens=sum(attempt.cache_write_tokens or 0 for attempt in attempts),
        known_cost_usd=sum((attempt.cost_usd for attempt in attempts if attempt.cost_usd is not None), start=Decimal(0)),
        token_completeness=completeness,
        cost_completeness=completeness,
    )


class GatewayRequestReportOut(BaseModel):
    request_id: UUID
    request_started_at: datetime
    org_id: UUID
    workspace_id: UUID
    workspace_label: str
    key_id: str
    authentication_source: AuthenticationSource
    authentication_label: str
    user_id: UUID
    principal_label: str
    principal_type: PrincipalType
    requested_model_id: str
    requested_capabilities: list[RequestCapability]
    bundle_id: UUID
    stream: bool
    terminal: RequestTerminalOut | None
    attempts: list[RequestAttemptOut]
    denial: DeniedRequestEvidenceOut | None
    evidence_complete: bool
    confidence: RequestConfidence
    known_input_tokens: int = Field(ge=0)
    known_output_tokens: int = Field(ge=0)
    known_cache_read_tokens: int = Field(ge=0)
    known_cache_write_tokens: int = Field(ge=0)
    known_cost_usd: UsdAmount
    token_completeness: AccountingCompleteness
    cost_completeness: AccountingCompleteness

    @model_validator(mode="after")
    def coherent_evidence(self) -> Self:
        attempt_indexes = [attempt.attempt_index for attempt in self.attempts]
        if attempt_indexes != sorted(set(attempt_indexes)):
            message = "request attempts must have unique ascending attempt indexes"
            raise ValueError(message)
        expected_attempts = self.terminal.expected_attempts if self.terminal is not None else None
        if expected_attempts is not None and any(index > expected_attempts for index in attempt_indexes):
            message = "request attempt index exceeds terminal expected attempts"
            raise ValueError(message)
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
                for attempt in self.attempts
            ],
        )
        if any(getattr(self, field) != getattr(accounting, field) for field in RequestAccountingOut.model_fields):
            message = "request accounting must match visible attempt evidence"
            raise ValueError(message)
        evidence = [*self.attempts, *([self.denial] if self.denial is not None else [])]
        if self.terminal is not None:
            if self.denial is not None and self.terminal.outcome != "denied":
                message = "denial evidence requires a denied terminal outcome"
                raise ValueError(message)
            if any(event.occurred_at > self.terminal.occurred_at for event in evidence):
                message = "request evidence must not occur after its terminal observation"
                raise ValueError(message)
        if self.denial is not None and any(attempt.occurred_at > self.denial.occurred_at for attempt in self.attempts):
            message = "routed attempts must not occur after denial evidence"
            raise ValueError(message)
        return self


class GatewayRequestPageOut(BaseModel):
    freshness: OverviewFreshnessOut
    period: OverviewPeriodOut
    items: list[GatewayRequestReportOut] = Field(max_length=200)
    page: PageInfo


class GatewayRequestDetailOut(BaseModel):
    freshness: OverviewFreshnessOut
    request: GatewayRequestReportOut


class GatewayRequestCsvExportOut(BaseModel):
    filename: str
    content_type: Literal["text/csv; charset=utf-8"] = "text/csv; charset=utf-8"
    row_count: int = Field(ge=0)
    freshness: OverviewFreshnessOut
    period: OverviewPeriodOut
    csv: str


class RequestExportTooLargeError(ValueError):
    def __init__(self) -> None:
        super().__init__("Request export is too large; narrow the filters")


def _safe_csv_text(value: str) -> str:
    stripped = value.lstrip()
    return f"'{value}" if value[:1] in {"\t", "\r", "\n"} or stripped[:1] in {"=", "+", "-", "@"} else value


CSV_FIELDS = (
    "request_id",
    "request_started_at",
    "outcome",
    "finished_at",
    "expected_attempts",
    "latency_ms",
    "workspace_id",
    "workspace_label",
    "key_id",
    "authentication_source",
    "authentication_label",
    "user_id",
    "principal_label",
    "principal_type",
    "requested_model_id",
    "bundle_id",
    "stream",
    "confidence",
    "evidence_complete",
    "known_input_tokens",
    "known_output_tokens",
    "known_cache_read_tokens",
    "known_cache_write_tokens",
    "known_cost_usd",
    "token_completeness",
    "cost_completeness",
    "attempts_json",
    "denial_json",
)


def build_request_csv(
    requests: list[GatewayRequestReportOut],
    *,
    max_rows: int | None = None,
    max_bytes: int | None = None,
) -> str:
    row_limit = MAX_EXPORT_ROWS if max_rows is None else max_rows
    byte_limit = MAX_EXPORT_BYTES if max_bytes is None else max_bytes
    if len(requests) > row_limit:
        raise RequestExportTooLargeError
    output = io.StringIO(newline="")
    header = io.StringIO(newline="")
    csv.DictWriter(header, fieldnames=CSV_FIELDS, lineterminator="\r\n").writeheader()
    header_text = header.getvalue()
    encoded_bytes = len(header_text.encode())
    if encoded_bytes > byte_limit:
        raise RequestExportTooLargeError
    output.write(header_text)
    for request in requests:
        terminal = request.terminal
        values = request.model_dump(mode="json")
        values["attempts"] = sorted(values["attempts"], key=lambda attempt: attempt["attempt_index"])
        row: dict[str, object] = {
            "request_id": str(request.request_id),
            "request_started_at": request.request_started_at.isoformat(),
            "outcome": terminal.outcome if terminal is not None else "pending",
            "finished_at": terminal.occurred_at.isoformat() if terminal is not None else "",
            "expected_attempts": terminal.expected_attempts if terminal is not None else "",
            "latency_ms": terminal.latency_ms if terminal is not None else "",
            "workspace_id": str(request.workspace_id),
            "workspace_label": _safe_csv_text(request.workspace_label),
            "key_id": _safe_csv_text(request.key_id),
            "authentication_source": request.authentication_source,
            "authentication_label": _safe_csv_text(request.authentication_label),
            "user_id": str(request.user_id),
            "principal_label": _safe_csv_text(request.principal_label),
            "principal_type": request.principal_type,
            "requested_model_id": _safe_csv_text(request.requested_model_id),
            "bundle_id": str(request.bundle_id),
            "stream": str(request.stream).lower(),
            "confidence": request.confidence,
            "evidence_complete": str(request.evidence_complete).lower(),
            "known_input_tokens": request.known_input_tokens,
            "known_output_tokens": request.known_output_tokens,
            "known_cache_read_tokens": request.known_cache_read_tokens,
            "known_cache_write_tokens": request.known_cache_write_tokens,
            "known_cost_usd": values["known_cost_usd"],
            "token_completeness": request.token_completeness,
            "cost_completeness": request.cost_completeness,
            "attempts_json": json.dumps(values["attempts"], separators=(",", ":"), ensure_ascii=False),
            "denial_json": json.dumps(values["denial"], separators=(",", ":"), ensure_ascii=False),
        }
        encoded_row = io.StringIO(newline="")
        csv.DictWriter(encoded_row, fieldnames=CSV_FIELDS, lineterminator="\r\n").writerow(row)
        row_text = encoded_row.getvalue()
        encoded_bytes += len(row_text.encode())
        if encoded_bytes > byte_limit:
            raise RequestExportTooLargeError
        output.write(row_text)
    return output.getvalue()
