from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from api_models import OverviewReportOut as GeneratedOverviewReportOut
from contract import uuid7
from control_plane.models.overview_report import (
    OverviewFreshnessOut,
    OverviewReportQuery,
    ReportFact,
    build_overview_report,
    resolve_periods,
)

if TYPE_CHECKING:
    from uuid import UUID


def _fact(request_id: UUID, started_at: datetime, *, user_id: UUID | None = None, cost: str = "0.000000000001") -> ReportFact:
    return ReportFact(
        request_id=request_id,
        request_started_at=started_at,
        workspace_id=uuid7(),
        workspace_label="Production",
        key_id="production-key",
        authentication_label="Production key",
        user_id=user_id or uuid7(),
        principal_label=str(user_id or "Checkout service"),
        outcome="succeeded",
        expected_attempts=1,
        visible_attempts=1,
        attempt_index=1,
        model_id="gpt-test",
        provider_id="openai",
        input_tokens=1,
        output_tokens=1,
        cache_read_tokens=0,
        cache_write_tokens=0,
        token_usage_source="provider",
        cost_source="catalog_estimate",
        cost_usd=Decimal(cost),
    )


def test_custom_dates_are_inclusive_local_days_and_comparison_has_equal_elapsed_time():
    query = OverviewReportQuery(
        range="custom",
        timezone="America/Los_Angeles",
        start_date=date(2026, 3, 8),
        end_date=date(2026, 3, 8),
    )

    periods = resolve_periods(query, datetime(2026, 3, 9, 12, tzinfo=UTC))

    assert periods.current.start_at == datetime(2026, 3, 8, 8, tzinfo=UTC)
    assert periods.current.end_at == datetime(2026, 3, 9, 7, tzinfo=UTC)
    assert periods.current.end_at - periods.current.start_at == periods.comparison.end_at - periods.comparison.start_at
    assert periods.comparison.end_at == periods.current.start_at


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"range": "custom", "timezone": "UTC"}, "start_date and end_date are required"),
        (
            {"range": "custom", "timezone": "UTC", "start_date": date(2026, 2, 2), "end_date": date(2026, 2, 1)},
            "start_date must be on or before end_date",
        ),
        ({"range": "7d", "timezone": "UTC", "start_date": date(2026, 2, 1)}, "only accepted for custom"),
        (
            {"range": "custom", "timezone": "UTC", "start_date": date(2025, 1, 1), "end_date": date(2026, 1, 2)},
            "must not exceed 366 inclusive days",
        ),
        ({"range": "today", "timezone": "Mars/Olympus"}, "valid IANA timezone"),
    ],
)
def test_report_query_rejects_inconsistent_calendar_inputs(values, message):
    with pytest.raises(ValueError, match=message):
        OverviewReportQuery(**values)


def test_today_uses_partial_local_day_and_equal_elapsed_comparison_across_fall_back():
    query = OverviewReportQuery(range="today", timezone="America/Los_Angeles")

    periods = resolve_periods(query, datetime(2026, 11, 1, 10, 30, tzinfo=UTC))

    assert periods.current.start_at == datetime(2026, 11, 1, 7, tzinfo=UTC)
    assert periods.current.end_at == datetime(2026, 11, 1, 10, 30, tzinfo=UTC)
    assert periods.comparison.start_at == datetime(2026, 11, 1, 3, 30, tzinfo=UTC)
    assert periods.comparison.end_at == periods.current.start_at


def test_hourly_series_keeps_both_fall_back_folds_distinct_and_reconciled():
    query = OverviewReportQuery(
        range="custom",
        timezone="America/Los_Angeles",
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 1),
        bucket="hour",
    )
    received_at = datetime(2026, 11, 2, 8, tzinfo=UTC)
    periods = resolve_periods(query, received_at)
    report = build_overview_report(
        query,
        OverviewFreshnessOut(watermark=None, received_at=received_at),
        periods,
        [
            _fact(uuid7(), datetime(2026, 11, 1, 8, 30, tzinfo=UTC)),
            _fact(uuid7(), datetime(2026, 11, 1, 9, 30, tzinfo=UTC)),
        ],
    )

    assert [point.start_at for point in report.series] == [
        datetime(2026, 11, 1, 8, tzinfo=UTC),
        datetime(2026, 11, 1, 9, tzinfo=UTC),
    ]
    assert sum(point.metrics.logical_requests for point in report.series) == report.summary.current.logical_requests == 2
    assert sum(point.metrics.attempts for point in report.series) == report.summary.current.attempts == 2


def test_attribution_share_is_fixed_point_and_generated_python_accepts_exponent_prone_ratio():
    query = OverviewReportQuery(
        range="custom",
        timezone="UTC",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 1),
        group="principal",
    )
    received_at = datetime(2026, 1, 2, tzinfo=UTC)
    periods = resolve_periods(query, received_at)
    small_principal = uuid7()
    report = build_overview_report(
        query,
        OverviewFreshnessOut(watermark=None, received_at=received_at),
        periods,
        [
            _fact(uuid7(), datetime(2026, 1, 1, 1, tzinfo=UTC), user_id=small_principal),
            _fact(uuid7(), datetime(2026, 1, 1, 2, tzinfo=UTC), cost="1.000000000000"),
        ],
    )

    payload = report.model_dump_json()
    GeneratedOverviewReportOut.model_validate_json(payload)
    small_share = next(item.share_of_known_cost for item in report.attribution if item.id == str(small_principal))
    assert small_share is not None
    assert f'"share_of_known_cost":"{format(small_share, "f")}"' in payload
    assert "E-" not in payload
