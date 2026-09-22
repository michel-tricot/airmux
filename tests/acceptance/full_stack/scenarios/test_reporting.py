from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import httpx
import yaml
from pydantic import TypeAdapter
from stack_harness import ADMIN_EMAIL, ADMIN_PASSWORD, MODEL, _payload, _poll

from api_models import (
    Attempts,
    GatewayRequestCsvExportOut,
    GatewayRequestDetailOut,
    GatewayRequestPageOut,
    ObservedRequestAttemptOut,
    OverviewMetricsOut,
    OverviewReportOut,
    UnavailableRequestAttemptOut,
)

if TYPE_CHECKING:
    from stack_harness import Stack


PRICES = {
    "input_price_per_mtok": "2",
    "output_price_per_mtok": "5",
    "cache_read_price_per_mtok": "0.25",
    "cache_write_price_per_mtok": "0.5",
}


@dataclass(frozen=True)
class FrozenReports:
    overview: OverviewReportOut
    page: GatewayRequestPageOut
    detail: GatewayRequestDetailOut
    exported: GatewayRequestCsvExportOut


@dataclass(frozen=True)
class ReportScope:
    stack: Stack
    authorization: dict[str, str]
    request_path: str
    route_query: dict[str, str]
    overview_query: dict[str, str]


def _configure_reporting(stack: Stack) -> None:
    fallback_action = {
        "kind": "fallback",
        "models": ["quirk"],
        "on": ["upstream_unavailable"],
        "max_attempts": 2,
        "timeout_ms": 10000,
    }
    with httpx.Client(base_url=stack.cp_url, headers={"X-Requested-With": "XMLHttpRequest"}, timeout=10) as admin:
        _payload(admin.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}))
        workspace = _payload(admin.get(f"/api/v1/organizations/{stack.org_id}/workspaces"))[0]
        models = yaml.safe_load((stack.tmp / "taxonomy.yml").read_text(encoding="utf-8"))["models"]
        for model in models:
            if model["model_id"] in {MODEL, "quirk"}:
                _payload(admin.post("/api/v1/instance/taxonomy/models", json={**model, **PRICES}))
        policy = _payload(
            admin.post(
                f"/api/v1/organizations/{stack.org_id}/workspaces/{workspace['id']}/policies",
                json={
                    "name": "Use the backup on unavailable",
                    "definition": {
                        "target": {"kind": "workspace"},
                        "rules": [
                            {
                                "match": {"kind": "all_requests"},
                                "action": fallback_action,
                            }
                        ],
                    },
                },
            )
        )
    operational = {"authorization": f"Bearer {stack.env['AIRMUX_DATAPLANE_TOKEN']}"}

    def reporting_bundle_ready() -> bool:
        manifest = _payload(httpx.get(f"{stack.cp_url}/api/v1/bundles/manifest", headers=operational, timeout=10))
        entry = next((entry for entry in manifest["bundles"] if entry["org_id"] == stack.org_id), None)
        if entry is None:
            return False
        bundle = _payload(httpx.get(f"{stack.cp_url}/api/v1/bundles/{entry['bundle_id']}", headers=operational, timeout=10))
        priced = {
            model["model_id"]
            for model in bundle["catalog"]["models"]
            if model["model_id"] in {MODEL, "quirk"} and all(Decimal(model[field]) == Decimal(value) for field, value in PRICES.items())
        }
        return (
            priced == {MODEL, "quirk"}
            and bool(bundle["keys"] and bundle["catalog"]["credentials"])
            and any(
                item["id"] == policy["id"] and item["definition"]["rules"] == [{"match": {"kind": "all_requests"}, "action": fallback_action}]
                for item in bundle["policies"]
            )
        )

    assert _poll(reporting_bundle_ready, 30), "the priced fallback bundle was not published"


def _request_page(stack: Stack, authorization: dict[str, str], path: str, query: dict[str, str]) -> GatewayRequestPageOut:
    response = httpx.get(stack.cp_url + path, headers=authorization, params=query, timeout=10)
    return GatewayRequestPageOut.model_validate(_payload(response))


def _wait_for_request_count(
    stack: Stack,
    authorization: dict[str, str],
    path: str,
    query: dict[str, str],
    expected: int,
) -> GatewayRequestPageOut:
    reconciled: list[GatewayRequestPageOut] = []

    def ready() -> bool:
        page = _request_page(stack, authorization, path, query)
        if len(page.items) != expected or not all(item.terminal is not None for item in page.items):
            return False
        reconciled.append(page)
        return True

    assert _poll(ready, 15), f"reporting did not reconcile {expected} logical requests"
    return reconciled[0]


def _frozen_reports(
    scope: ReportScope,
    request_id: str,
    as_of: str,
) -> FrozenReports:
    frozen_route_query = {**scope.route_query, "as_of": as_of}
    overview = OverviewReportOut.model_validate(
        _payload(
            httpx.get(
                f"{scope.stack.cp_url}/api/v1/organizations/{scope.stack.org_id}/reports/overview",
                headers=scope.authorization,
                params={**scope.overview_query, "as_of": as_of},
                timeout=10,
            )
        )
    )
    detail = GatewayRequestDetailOut.model_validate(
        _payload(
            httpx.get(
                scope.stack.cp_url + scope.request_path + f"/{request_id}",
                headers=scope.authorization,
                params={"as_of": as_of},
                timeout=10,
            )
        )
    )
    exported = GatewayRequestCsvExportOut.model_validate(
        _payload(
            httpx.get(
                f"{scope.stack.cp_url}/api/v1/organizations/{scope.stack.org_id}/reports/request-export",
                headers=scope.authorization,
                params=frozen_route_query,
                timeout=10,
            )
        )
    )
    return FrozenReports(
        overview=overview,
        page=_request_page(scope.stack, scope.authorization, scope.request_path, frozen_route_query),
        detail=detail,
        exported=exported,
    )


def _assert_rates(attempt: ObservedRequestAttemptOut | UnavailableRequestAttemptOut) -> None:
    assert Decimal(attempt.input_price_per_mtok) == Decimal(2)
    assert Decimal(attempt.output_price_per_mtok) == Decimal(5)
    assert Decimal(attempt.cache_read_price_per_mtok) == Decimal("0.25")
    assert Decimal(attempt.cache_write_price_per_mtok) == Decimal("0.5")


def _assert_attempts(attempts: list[Attempts]) -> None:
    assert [attempt.root.attempt_index for attempt in attempts] == [1, 2]
    first, second = (attempt.root for attempt in attempts)
    assert isinstance(first, UnavailableRequestAttemptOut)
    assert (first.model_id, first.provider_id, first.status, first.token_usage_source) == (MODEL, "stub", "upstream_error", "unavailable")
    assert (first.input_tokens, first.output_tokens, first.cache_read_tokens, first.cache_write_tokens, first.cost_usd) == (
        None,
        None,
        None,
        None,
        None,
    )
    _assert_rates(first)
    assert isinstance(second, ObservedRequestAttemptOut)
    assert (second.model_id, second.provider_id, second.status, second.token_usage_source) == ("quirk", "quirk", "ok", "provider")
    assert (second.input_tokens, second.output_tokens, second.cache_read_tokens, second.cache_write_tokens) == (11, 3, 4, 0)
    assert second.input_tokens - second.cache_read_tokens - second.cache_write_tokens == 7
    _assert_rates(second)
    assert Decimal(second.cost_input_usd) == Decimal("0.000015")
    assert Decimal(second.cost_output_usd) == Decimal("0.000015")
    assert Decimal(second.cost_usd) == Decimal("0.000030")


def _assert_overall_metrics(metrics: OverviewMetricsOut) -> None:
    assert (metrics.logical_requests, metrics.attempts, metrics.pending_requests, metrics.incomplete_requests) == (1, 2, 0, 0)
    assert (metrics.outcomes.succeeded, metrics.outcomes.failed, metrics.outcomes.denied, metrics.outcomes.timeout, metrics.outcomes.cancelled) == (
        1,
        0,
        0,
        0,
        0,
    )
    assert (metrics.known_input_tokens, metrics.known_output_tokens, metrics.known_cache_read_tokens, metrics.known_cache_write_tokens) == (
        11,
        3,
        4,
        0,
    )
    assert (
        metrics.token_sources.provider,
        metrics.token_sources.estimated,
        metrics.token_sources.partial,
        metrics.token_sources.unavailable,
        metrics.token_sources.not_applicable,
    ) == (
        1,
        0,
        0,
        1,
        0,
    )
    assert (metrics.unavailable_usage_attempts, metrics.unpriced_attempts) == (1, 1)
    assert (metrics.cost_sources.catalog_estimate, metrics.cost_sources.unavailable, metrics.cost_sources.not_applicable) == (1, 1, 0)
    assert Decimal(metrics.known_cost_usd) == Decimal("0.000030")
    assert metrics.cost_per_request_usd is not None
    assert Decimal(metrics.cost_per_request_usd.root) == Decimal("0.000030")
    assert metrics.cost_per_request_denominator == 1
    assert (metrics.token_completeness, metrics.cost_completeness) == ("partial", "partial")


def _assert_provider_metrics(metrics: OverviewMetricsOut, provider: str) -> None:
    if provider == "stub":
        assert (
            metrics.logical_requests,
            metrics.attempts,
            metrics.known_input_tokens,
            metrics.known_output_tokens,
            metrics.known_cache_read_tokens,
            metrics.known_cache_write_tokens,
        ) == (0, 1, 0, 0, 0, 0)
        assert (
            metrics.token_sources.provider,
            metrics.token_sources.estimated,
            metrics.token_sources.partial,
            metrics.token_sources.unavailable,
            metrics.token_sources.not_applicable,
            metrics.unavailable_usage_attempts,
        ) == (0, 0, 0, 1, 0, 1)
        assert (
            metrics.cost_sources.catalog_estimate,
            metrics.cost_sources.unavailable,
            metrics.cost_sources.not_applicable,
            metrics.unpriced_attempts,
        ) == (
            0,
            1,
            0,
            1,
        )
        assert (
            metrics.outcomes.succeeded,
            metrics.outcomes.failed,
            metrics.outcomes.denied,
            metrics.outcomes.timeout,
            metrics.outcomes.cancelled,
        ) == (
            0,
            0,
            0,
            0,
            0,
        )
        assert (Decimal(metrics.known_cost_usd), metrics.cost_per_request_usd, metrics.cost_per_request_denominator) == (Decimal(0), None, 0)
        assert (metrics.pending_requests, metrics.incomplete_requests, metrics.token_completeness, metrics.cost_completeness) == (
            0,
            0,
            "unavailable",
            "unavailable",
        )
        return
    assert (metrics.logical_requests, metrics.attempts, metrics.known_input_tokens, metrics.known_output_tokens) == (1, 1, 11, 3)
    assert (metrics.known_cache_read_tokens, metrics.known_cache_write_tokens) == (4, 0)
    assert (
        metrics.token_sources.provider,
        metrics.token_sources.estimated,
        metrics.token_sources.partial,
        metrics.token_sources.unavailable,
        metrics.token_sources.not_applicable,
        metrics.unavailable_usage_attempts,
    ) == (1, 0, 0, 0, 0, 0)
    assert (
        metrics.cost_sources.catalog_estimate,
        metrics.cost_sources.unavailable,
        metrics.cost_sources.not_applicable,
        metrics.unpriced_attempts,
    ) == (1, 0, 0, 0)
    assert (metrics.outcomes.succeeded, metrics.outcomes.failed, metrics.outcomes.denied, metrics.outcomes.timeout, metrics.outcomes.cancelled) == (
        1,
        0,
        0,
        0,
        0,
    )
    assert Decimal(metrics.known_cost_usd) == Decimal("0.000030")
    assert metrics.cost_per_request_usd is not None
    assert Decimal(metrics.cost_per_request_usd.root) == Decimal("0.000030")
    assert (
        metrics.cost_per_request_denominator,
        metrics.pending_requests,
        metrics.incomplete_requests,
        metrics.token_completeness,
        metrics.cost_completeness,
    ) == (
        1,
        0,
        0,
        "complete",
        "complete",
    )


def _assert_overview(overview: OverviewReportOut) -> None:
    assert (overview.bucket.root, overview.split.root, overview.group.root) == ("hour", "provider", "provider")
    _assert_overall_metrics(overview.summary.current)
    series = {point.split_id: point.metrics for point in overview.series}
    attribution = {item.id: item for item in overview.attribution}
    assert set(series) == set(attribution) == {"stub", "quirk"}
    for provider in ("stub", "quirk"):
        _assert_provider_metrics(series[provider], provider)
        _assert_provider_metrics(attribution[provider].summary.current, provider)
    assert attribution["stub"].share_of_known_cost is not None
    assert attribution["quirk"].share_of_known_cost is not None
    assert Decimal(attribution["stub"].share_of_known_cost.root) == 0
    assert Decimal(attribution["quirk"].share_of_known_cost.root) == 1


def _assert_csv(exported: GatewayRequestCsvExportOut, request_id: str) -> None:
    (request,) = list(csv.DictReader(io.StringIO(exported.csv)))
    assert request["request_id"] == request_id
    assert (request["outcome"], request["expected_attempts"], request["confidence"], request["evidence_complete"]) == (
        "succeeded",
        "2",
        "unavailable",
        "true",
    )
    assert (
        request["known_input_tokens"],
        request["known_output_tokens"],
        request["known_cache_read_tokens"],
        request["known_cache_write_tokens"],
    ) == ("11", "3", "4", "0")
    assert request["known_cost_usd"] is not None
    assert Decimal(request["known_cost_usd"]) == Decimal("0.000030")
    attempts_json = request["attempts_json"]
    assert attempts_json is not None
    _assert_attempts(TypeAdapter(list[Attempts]).validate_json(attempts_json))


def _assert_frozen_reports(reports: FrozenReports, request_id: str, as_of: str) -> None:
    assert {reports.overview.freshness.as_of, reports.page.freshness.as_of, reports.detail.freshness.as_of, reports.exported.freshness.as_of} == {
        as_of
    }
    assert reports.overview.periods.current == reports.page.period == reports.exported.period
    assert (reports.overview.summary.current.logical_requests, reports.overview.summary.current.attempts, reports.exported.row_count) == (1, 2, 1)
    (listed,) = reports.page.items
    assert reports.detail.request == listed
    assert str(listed.request_id) == request_id
    assert listed.terminal is not None
    assert (listed.terminal.outcome, listed.terminal.expected_attempts) == ("succeeded", 2)
    assert (listed.evidence_complete, listed.confidence, listed.token_completeness, listed.cost_completeness) == (
        True,
        "unavailable",
        "partial",
        "partial",
    )
    _assert_attempts(listed.attempts)
    _assert_overview(reports.overview)
    _assert_csv(reports.exported, request_id)
    assert Decimal(listed.known_cost_usd) == Decimal(reports.overview.summary.current.known_cost_usd) == Decimal("0.000030")


def test_running_gateway_reports_reconcile_retries_and_freeze_snapshots(stack: Stack) -> None:
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    _configure_reporting(stack)
    stack.start_dp()
    stack.wait_dp_ready()

    first_response = stack.request("fallback-primary-unavailable")
    assert first_response.status_code == 200, first_response.text
    first_request_id = first_response.headers["x-request-id"]
    authorization = {"authorization": f"Bearer {stack.env['AIRMUX_MANAGEMENT_KEY']}"}
    request_path = f"/api/v1/organizations/{stack.org_id}/reports/requests"
    route_query = {"range": "7d", "timezone": "UTC", "model": "quirk", "provider": "quirk"}
    overview_query = {**route_query, "bucket": "hour", "split": "provider", "group": "provider"}
    scope = ReportScope(stack, authorization, request_path, route_query, overview_query)
    initial = _wait_for_request_count(stack, authorization, request_path, route_query, 1)
    as_of = initial.freshness.as_of
    before = _frozen_reports(scope, first_request_id, as_of)

    second_response = stack.request("fallback-primary-unavailable")
    assert second_response.status_code == 200, second_response.text
    second_request_id = second_response.headers["x-request-id"]
    assert second_request_id != first_request_id
    latest = _wait_for_request_count(stack, authorization, request_path, route_query, 2)
    assert {str(item.request_id) for item in latest.items} == {first_request_id, second_request_id}

    after = _frozen_reports(scope, first_request_id, as_of)
    assert after == before
    _assert_frozen_reports(after, first_request_id, as_of)
