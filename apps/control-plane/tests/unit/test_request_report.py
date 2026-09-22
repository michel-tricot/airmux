from __future__ import annotations

import base64
import csv
import io
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from contract import TokenUsageSource, uuid7
from control_plane.models.common.pagination import InvalidCursorError
from control_plane.models.overview_report import OverviewPeriodOut, ReportSnapshotV1, encode_report_snapshot
from control_plane.models.request_report import (
    GatewayRequestReportOut,
    ObservedRequestAttemptOut,
    OrgRequestReportQuery,
    RequestAttemptFact,
    RequestCostAnchor,
    RequestCursorV1,
    RequestExportTooLargeError,
    RequestLatencyAnchor,
    RequestStartedAtAnchor,
    RequestTerminalOut,
    RequestTokensAnchor,
    WorkspaceRequestReportQuery,
    build_request_accounting,
    build_request_csv,
    decode_request_cursor,
    encode_request_cursor,
    request_query_fingerprint,
    validate_request_cursor,
)

if TYPE_CHECKING:
    from uuid import UUID


def _period() -> OverviewPeriodOut:
    return OverviewPeriodOut(
        start_at=datetime(2026, 1, 1, tzinfo=UTC),
        end_at=datetime(2026, 1, 8, tzinfo=UTC),
        timezone="UTC",
    )


def _as_of(org_id: UUID, workspace_id: UUID | None = None) -> str:
    return encode_report_snapshot(
        ReportSnapshotV1(
            watermark=uuid7(),
            resolved_at=datetime(2026, 1, 8, tzinfo=UTC),
            org_id=org_id,
            workspace_id=workspace_id,
        )
    )


def _query(**values: object) -> OrgRequestReportQuery:
    return OrgRequestReportQuery.model_validate({"range": "7d", "timezone": "UTC", **values})


def _attempt(
    source: TokenUsageSource = TokenUsageSource.PROVIDER,
    *,
    tokens: tuple[int | None, int | None, int | None, int | None] = (3, 4, 1, 0),
    cost_usd: Decimal | None = Decimal("0.000000000001"),
) -> RequestAttemptFact:
    input_tokens, output_tokens, cache_read_tokens, cache_write_tokens = tokens
    return RequestAttemptFact(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        token_usage_source=source,
        cost_usd=cost_usd,
    )


def _unavailable_attempt() -> RequestAttemptFact:
    return _attempt(
        source=TokenUsageSource.UNAVAILABLE,
        tokens=(None, None, None, None),
        cost_usd=None,
    )


def _export_attempt(index: int) -> ObservedRequestAttemptOut:
    return ObservedRequestAttemptOut(
        event_id=uuid7(),
        attempt_index=index,
        attempt_started_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        occurred_at=datetime(2026, 1, 2, 3, 4, 6, tzinfo=UTC),
        model_id=f"model-{index}",
        provider_id=f"provider-{index}",
        input_tokens=index,
        output_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
        token_usage_source=TokenUsageSource.PROVIDER,
        max_output_tokens=10,
        input_price_per_mtok=Decimal(0),
        output_price_per_mtok=Decimal(0),
        cache_read_price_per_mtok=Decimal(0),
        cache_write_price_per_mtok=Decimal(0),
        cost_source="catalog_estimate",
        cost_usd=Decimal("0.000000000001"),
        cost_input_usd=Decimal("0.000000000001"),
        cost_output_usd=Decimal(0),
        latency_ms=1,
        status="ok",
        credential_id=uuid7(),
        credential_scope="workspace",
        credential_name=f"credential-{index}",
    )


def _export_row(*, request_id: UUID | None = None, attempt_indexes: tuple[int, ...] = (1, 2)) -> GatewayRequestReportOut:
    attempts = [_export_attempt(index) for index in attempt_indexes]
    accounting = build_request_accounting(
        2,
        [
            RequestAttemptFact(
                input_tokens=attempt.input_tokens,
                output_tokens=attempt.output_tokens,
                cache_read_tokens=attempt.cache_read_tokens,
                cache_write_tokens=attempt.cache_write_tokens,
                token_usage_source=attempt.token_usage_source,
                cost_usd=attempt.cost_usd,
            )
            for attempt in attempts
        ],
    )
    return GatewayRequestReportOut(
        request_id=request_id or uuid7(),
        request_started_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        org_id=uuid7(),
        workspace_id=uuid7(),
        workspace_label="Pr\u00f8duction, west",
        key_id="checkout-key",
        authentication_source="local",
        authentication_label='=HYPERLINK("https://example.test")',
        user_id=uuid7(),
        principal_label="Checkout\nservice",
        principal_type="local",
        requested_model_id="gpt-test",
        requested_capabilities=[],
        bundle_id=uuid7(),
        stream=False,
        terminal=RequestTerminalOut(
            event_id=uuid7(),
            occurred_at=datetime(2026, 1, 2, 3, 4, 7, tzinfo=UTC),
            outcome="succeeded",
            expected_attempts=2,
            latency_ms=123,
        ),
        attempts=attempts,
        denial=None,
        **accounting.model_dump(),
    )


def test_query_trims_search_and_string_filters_without_mutating_closed_values():
    credential_id = uuid7()
    query = _query(
        search="  checkout  ",
        inference_key=["  checkout-key  "],
        model=["  gpt-test  "],
        provider=["  openai  "],
        provider_credential=[credential_id, "unattributed"],
        outcome=["succeeded"],
        confidence=["provider"],
    )

    assert query.search == "checkout"
    assert query.inference_key == ["checkout-key"]
    assert query.model == ["gpt-test"]
    assert query.provider == ["openai"]
    assert query.provider_credential == [credential_id, "unattributed"]
    assert query.outcome == ["succeeded"]
    assert query.confidence == ["provider"]


@pytest.mark.parametrize(
    "values",
    [
        {"search": "   "},
        {"search": "x" * 321},
        {"model": [f"model-{index}" for index in range(51)]},
        {"provider": ["   "]},
        {"provider_credential": ["not-a-uuid"]},
        {"provider_credential": [str(uuid7()) for _ in range(51)]},
        {"limit": 0},
        {"limit": 201},
        {"outcome": ["unknown"]},
        {"confidence": ["certain"]},
        {"unexpected": "value"},
    ],
)
def test_query_rejects_blank_oversized_unknown_and_out_of_range_values(values):
    with pytest.raises(ValidationError):
        _query(**values)


def test_org_and_workspace_queries_have_distinct_scope_fields():
    workspace_id = uuid7()

    query = OrgRequestReportQuery(
        range="custom",
        timezone="UTC",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
        workspace=[workspace_id],
    )

    assert query.workspace == [workspace_id]
    with pytest.raises(ValidationError):
        WorkspaceRequestReportQuery.model_validate({"range": "7d", "timezone": "UTC", "workspace": [workspace_id]})


@pytest.mark.parametrize(
    "anchor",
    [
        RequestStartedAtAnchor(
            request_started_at=datetime(2026, 1, 2, tzinfo=UTC),
            request_id=uuid7(),
        ),
        RequestLatencyAnchor(
            null_rank=0,
            latency_ms=123,
            request_started_at=datetime(2026, 1, 2, tzinfo=UTC),
            request_id=uuid7(),
        ),
        RequestCostAnchor(
            known_cost_usd=Decimal("0.000000000001"),
            request_started_at=datetime(2026, 1, 2, tzinfo=UTC),
            request_id=uuid7(),
        ),
        RequestTokensAnchor(
            known_tokens=7,
            request_started_at=datetime(2026, 1, 2, tzinfo=UTC),
            request_id=uuid7(),
        ),
    ],
)
def test_cursor_v1_round_trips_each_strict_anchor(anchor):
    query = _query(sort=anchor.kind)
    period = _period()
    org_id = uuid7()
    cursor = RequestCursorV1(
        as_of=_as_of(org_id),
        sort=query.sort,
        direction=query.direction,
        anchor=anchor,
        fingerprint=request_query_fingerprint(query, org_id, None, period),
    )

    token = encode_request_cursor(cursor)
    decoded = decode_request_cursor(token)

    assert len(token) <= 512
    assert decoded.version == 1
    assert decoded == cursor
    validate_request_cursor(decoded, query, org_id, None, period)


def test_query_fingerprint_binds_filters_scope_period_and_sort_but_not_page_transport():
    org_id = uuid7()
    workspace_id = uuid7()
    period = _period()
    base = _query(search="checkout", limit=25)
    fingerprint = request_query_fingerprint(base, org_id, None, period)

    assert request_query_fingerprint(_query(search="checkout", limit=200), org_id, None, period) == fingerprint
    assert request_query_fingerprint(_query(search="other", limit=25), org_id, None, period) != fingerprint
    assert request_query_fingerprint(_query(search="checkout", provider_credential=[uuid7()]), org_id, None, period) != fingerprint
    assert request_query_fingerprint(_query(search="checkout", sort="latency_ms"), org_id, None, period) != fingerprint
    assert request_query_fingerprint(base, org_id, workspace_id, period) != fingerprint
    shifted = period.model_copy(update={"end_at": datetime(2026, 1, 9, tzinfo=UTC)})
    assert request_query_fingerprint(base, org_id, None, shifted) != fingerprint


def test_cursor_validation_rejects_changed_query_scope_period_and_as_of():
    org_id = uuid7()
    period = _period()
    query = _query(search="checkout")
    cursor = RequestCursorV1(
        as_of=_as_of(org_id),
        sort=query.sort,
        direction=query.direction,
        anchor=RequestStartedAtAnchor(request_started_at=datetime(2026, 1, 2, tzinfo=UTC), request_id=uuid7()),
        fingerprint=request_query_fingerprint(query, org_id, None, period),
    )

    changed_period = period.model_copy(update={"end_at": datetime(2026, 1, 9, tzinfo=UTC)})
    for changed_query, changed_org, changed_workspace, changed_bounds in [
        (_query(search="other"), org_id, None, period),
        (query, uuid7(), None, period),
        (query, org_id, uuid7(), period),
        (query, org_id, None, changed_period),
        (_query(search="checkout", as_of=_as_of(org_id)), org_id, None, period),
    ]:
        with pytest.raises(InvalidCursorError):
            validate_request_cursor(cursor, changed_query, changed_org, changed_workspace, changed_bounds)


@pytest.mark.parametrize("token", ["not+a+cursor", "e30", "A" * 513])
def test_cursor_decode_rejects_malformed_or_oversized_tokens(token):
    with pytest.raises(InvalidCursorError):
        decode_request_cursor(token)


def test_cursor_rejects_canonically_reencoded_caller_period_bounds():
    org_id = uuid7()
    period = _period()
    query = _query()
    cursor = RequestCursorV1(
        as_of=_as_of(org_id),
        sort=query.sort,
        direction=query.direction,
        anchor=RequestStartedAtAnchor(request_started_at=datetime(2026, 1, 2, tzinfo=UTC), request_id=uuid7()),
        fingerprint=request_query_fingerprint(query, org_id, None, period),
    )
    token = encode_request_cursor(cursor)
    payload = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    payload["p"] = ["2000-01-01T00:00:00+00:00", "2100-01-01T00:00:00+00:00"]
    forged = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()).decode().rstrip("=")

    with pytest.raises(InvalidCursorError):
        decode_request_cursor(forged)


def test_snapshot_and_cursor_anchors_reject_naive_datetimes():
    naive = datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None)
    with pytest.raises(ValidationError):
        ReportSnapshotV1(watermark=None, resolved_at=naive, org_id=uuid7(), workspace_id=None)
    with pytest.raises(ValidationError):
        RequestStartedAtAnchor(request_started_at=naive, request_id=uuid7())


def test_cursor_rejects_tampered_fingerprint_and_sort_anchor_mismatch():
    org_id = uuid7()
    period = _period()
    query = _query()
    cursor = RequestCursorV1(
        as_of=_as_of(org_id),
        sort=query.sort,
        direction=query.direction,
        anchor=RequestStartedAtAnchor(request_started_at=datetime(2026, 1, 2, tzinfo=UTC), request_id=uuid7()),
        fingerprint="0" * 64,
    )

    with pytest.raises(InvalidCursorError):
        validate_request_cursor(cursor, query, org_id, None, period)
    with pytest.raises(ValidationError):
        RequestCursorV1(
            as_of=_as_of(org_id),
            sort="latency_ms",
            direction="desc",
            anchor=RequestStartedAtAnchor(request_started_at=datetime(2026, 1, 2, tzinfo=UTC), request_id=uuid7()),
            fingerprint="0" * 64,
        )
    with pytest.raises(ValidationError):
        RequestCursorV1.model_validate(
            {
                "version": 2,
                "as_of": _as_of(org_id),
                "sort": query.sort,
                "direction": query.direction,
                "anchor": RequestStartedAtAnchor(request_started_at=datetime(2026, 1, 2, tzinfo=UTC), request_id=uuid7()),
                "fingerprint": "0" * 64,
            }
        )


@pytest.mark.parametrize(
    ("expected_attempts", "attempts", "confidence", "token_completeness", "cost_completeness"),
    [
        (None, [], "unavailable", "unavailable", "unavailable"),
        (0, [], "not_applicable", "complete", "complete"),
        (2, [_attempt()], "partial", "partial", "partial"),
        (1, [_attempt()], "provider", "complete", "complete"),
        (2, [_attempt(), _attempt(source=TokenUsageSource.ESTIMATED)], "estimated", "complete", "complete"),
        (1, [_attempt(source=TokenUsageSource.PARTIAL)], "partial", "complete", "complete"),
        (2, [_attempt(), _unavailable_attempt()], "unavailable", "partial", "partial"),
        (1, [_unavailable_attempt()], "unavailable", "unavailable", "unavailable"),
    ],
)
def test_accounting_and_confidence_precedence(expected_attempts, attempts, confidence, token_completeness, cost_completeness):
    accounting = build_request_accounting(expected_attempts, attempts)

    assert accounting.confidence == confidence
    assert accounting.token_completeness == token_completeness
    assert accounting.cost_completeness == cost_completeness


def test_accounting_preserves_exact_known_subtotals_and_distinguishes_zero_from_unknown():
    exact = build_request_accounting(2, [_attempt(), _unavailable_attempt()])
    zero = build_request_accounting(1, [_attempt(tokens=(0, 0, 0, 0), cost_usd=Decimal(0))])

    assert exact.known_input_tokens == 3
    assert exact.known_output_tokens == 4
    assert exact.known_cost_usd == Decimal("0.000000000001")
    assert '"known_cost_usd":"0.000000000001"' in exact.model_dump_json()
    assert zero.known_input_tokens == 0
    assert zero.known_output_tokens == 0
    assert zero.known_cost_usd == 0
    assert zero.token_completeness == "complete"


def test_csv_is_one_row_per_request_with_exact_values_safe_text_and_ordered_attempt_json():
    request_id = uuid7()
    payload = build_request_csv([_export_row(request_id=request_id)])
    rows = list(csv.DictReader(io.StringIO(payload)))

    assert len(rows) == 1
    row = rows[0]
    assert row["request_id"] == str(request_id)
    assert row["known_cost_usd"] == "0.000000000002"
    assert row["workspace_label"] == "Pr\u00f8duction, west"
    assert row["principal_label"] == "Checkout\nservice"
    assert row["authentication_label"].startswith("'=")
    attempts = json.loads(row["attempts_json"])
    assert [attempt["attempt_index"] for attempt in attempts] == [1, 2]
    assert all(attempt["cost_usd"] == "0.000000000001" for attempt in attempts)


def test_request_output_rejects_unordered_duplicate_attempts_and_mismatched_accounting():
    request = _export_row()
    values = request.model_dump()
    values["attempts"] = list(reversed(values["attempts"]))
    with pytest.raises(ValidationError):
        GatewayRequestReportOut.model_validate(values)

    values = request.model_dump()
    values["attempts"] = [values["attempts"][0], *values["attempts"]]
    with pytest.raises(ValidationError):
        GatewayRequestReportOut.model_validate(values)

    values = request.model_dump()
    values["known_cost_usd"] = Decimal(9)
    with pytest.raises(ValidationError):
        GatewayRequestReportOut.model_validate(values)


def test_request_output_rejects_denial_or_attempt_evidence_after_a_successful_terminal():
    request = _export_row()
    assert request.terminal is not None
    values = request.model_dump()
    values["denial"] = {
        "event_id": uuid7(),
        "occurred_at": request.terminal.occurred_at,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "token_usage_source": "not_applicable",
        "cost_source": "not_applicable",
        "cost_usd": Decimal(0),
        "cost_input_usd": Decimal(0),
        "cost_output_usd": Decimal(0),
        "latency_ms": 1,
        "status": "denied",
    }
    with pytest.raises(ValidationError):
        GatewayRequestReportOut.model_validate(values)

    values = request.model_dump()
    values["attempts"][1]["occurred_at"] = request.terminal.occurred_at + timedelta(microseconds=1)
    with pytest.raises(ValidationError):
        GatewayRequestReportOut.model_validate(values)


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r", "\n", "  ="])
def test_csv_neutralizes_spreadsheet_formula_prefixes(prefix: str):
    row = _export_row().model_copy(update={"authentication_label": f"{prefix}payload"})

    exported = next(csv.DictReader(io.StringIO(build_request_csv([row]))))

    assert exported["authentication_label"].startswith("'")


def test_csv_keeps_null_distinct_from_known_zero():
    unavailable_accounting = build_request_accounting(None, [])
    unavailable = _export_row().model_copy(update={**unavailable_accounting.model_dump(), "terminal": None, "attempts": []})
    zero_accounting = build_request_accounting(1, [_attempt(tokens=(0, 0, 0, 0), cost_usd=Decimal(0))])
    zero = _export_row(attempt_indexes=(1,)).model_copy(update=zero_accounting.model_dump())

    rows = list(csv.DictReader(io.StringIO(build_request_csv([unavailable, zero]))))

    assert rows[0]["known_cost_usd"] == "0"
    assert rows[0]["cost_completeness"] == "unavailable"
    assert rows[1]["known_cost_usd"] == "0"
    assert rows[1]["cost_completeness"] == "complete"


def test_csv_rejects_row_and_encoded_byte_overflow_without_returning_a_partial_export():
    row = _export_row()

    with pytest.raises(RequestExportTooLargeError):
        build_request_csv([row, row], max_rows=1)
    with pytest.raises(RequestExportTooLargeError):
        build_request_csv([row], max_bytes=16)
