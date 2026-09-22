from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient
from helpers import make_org, make_workspace, run_in_db, setup_control_plane

from api_models import OverviewReportOut
from contract import uuid7
from control_plane.authz import Permission
from control_plane.models import UsageIngestBatch

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True)
class RequestSeed:
    org_id: UUID
    workspace_id: UUID
    request_id: UUID
    started_at: datetime
    user_id: UUID
    key_id: str = "key-production"


def _attempt(  # noqa: PLR0913 event fixture exposes attribution dimensions
    seed: RequestSeed,
    *,
    attempt_index: int,
    model: str = "gpt-test",
    provider: str = "openai",
    cost: str | None = "0.000000000123",
    credential_id: UUID | None = None,
    credential_name: str = "default",
    credential_scope: str = "workspace",
) -> dict:
    source = "provider" if cost is not None else "unavailable"
    tokens = 10 if cost is not None else None
    return {
        "event_type": "usage",
        "event_id": str(uuid7()),
        "request_id": str(seed.request_id),
        "request_started_at": seed.started_at.isoformat(),
        "attempt_started_at": (seed.started_at + timedelta(milliseconds=10 * attempt_index)).isoformat(),
        "occurred_at": (seed.started_at + timedelta(milliseconds=50 * attempt_index)).isoformat(),
        "org_id": str(seed.org_id),
        "workspace_id": str(seed.workspace_id),
        "key_id": seed.key_id,
        "authentication_source": "inference_key",
        "authentication_label": "Production key",
        "user_id": str(seed.user_id),
        "principal_label": "Checkout service",
        "principal_type": "service_account",
        "workspace_label": "Production",
        "requested_model_id": "requested-model",
        "requested_capabilities": [],
        "model_id": model,
        "provider_id": provider,
        "bundle_id": str(uuid7()),
        "input_tokens": tokens,
        "output_tokens": 5 if tokens is not None else None,
        "token_usage_source": source,
        "attempt_index": attempt_index,
        "max_output_tokens": 128,
        "input_price_per_mtok": "1",
        "output_price_per_mtok": "2",
        "cache_read_price_per_mtok": "0.1",
        "cache_write_price_per_mtok": "1.25",
        "cost_source": "catalog_estimate" if cost is not None else "unavailable",
        "cost_usd": cost,
        "cost_input_usd": cost,
        "cost_output_usd": "0" if cost is not None else None,
        "cache_read_tokens": 0 if tokens is not None else None,
        "cache_write_tokens": 0 if tokens is not None else None,
        "latency_ms": 50,
        "status": "ok" if attempt_index == 2 else "upstream_error",
        "stream": False,
        "credential_id": str(credential_id or uuid7()),
        "credential_scope": credential_scope,
        "credential_name": credential_name,
    }


def _terminal(attempt: dict, *, expected_attempts: int, outcome: str = "succeeded") -> dict:
    return {
        "event_type": "gateway_request_finished",
        "schema_version": 1,
        "event_id": str(uuid7()),
        "request_id": attempt["request_id"],
        "request_started_at": attempt["request_started_at"],
        "occurred_at": attempt["occurred_at"],
        "org_id": attempt["org_id"],
        "workspace_id": attempt["workspace_id"],
        "key_id": attempt["key_id"],
        "authentication_source": attempt["authentication_source"],
        "authentication_label": attempt["authentication_label"],
        "user_id": attempt["user_id"],
        "principal_label": attempt["principal_label"],
        "principal_type": attempt["principal_type"],
        "workspace_label": attempt["workspace_label"],
        "requested_model_id": attempt["requested_model_id"],
        "requested_capabilities": attempt["requested_capabilities"],
        "bundle_id": attempt["bundle_id"],
        "stream": attempt["stream"],
        "outcome": outcome,
        "expected_attempts": expected_attempts,
        "latency_ms": 100,
    }


def _denial(attempt: dict) -> dict:
    return {
        **attempt,
        "event_id": str(uuid7()),
        "attempt_index": None,
        "attempt_started_at": None,
        "provider_id": "",
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "token_usage_source": "not_applicable",
        "input_price_per_mtok": None,
        "output_price_per_mtok": None,
        "cache_read_price_per_mtok": None,
        "cache_write_price_per_mtok": None,
        "cost_source": "not_applicable",
        "cost_usd": "0",
        "cost_input_usd": "0",
        "cost_output_usd": "0",
        "status": "denied",
        "credential_id": None,
        "credential_scope": None,
        "credential_name": None,
    }


def _overview(client: TestClient, org_id: UUID, headers: dict[str, str], **params):
    response = client.get(
        f"/api/v1/organizations/{org_id}/reports/overview",
        params={"range": "7d", "timezone": "UTC", **params},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_overview_reconciles_retry_attempts_under_a_stable_watermark(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "overview-retries")
        workspace_id = make_workspace(client, cp.headers(org_id), "production")
        request_id = uuid7()
        principal_id = uuid7()
        started_at = datetime.now(tz=UTC) - timedelta(hours=1)
        seed = RequestSeed(org_id, workspace_id, request_id, started_at, principal_id)
        first = _attempt(seed, attempt_index=1)
        first["token_usage_source"] = "estimated"
        second = {
            **first,
            "event_id": str(uuid7()),
            "attempt_index": 2,
            "attempt_started_at": (started_at + timedelta(milliseconds=20)).isoformat(),
            "occurred_at": (started_at + timedelta(milliseconds=100)).isoformat(),
            "model_id": "fallback-model",
            "provider_id": "anthropic",
            "cost_usd": "0.000000000321",
            "cost_input_usd": "0.000000000321",
            "token_usage_source": "partial",
            "status": "ok",
        }
        terminal = _terminal(first, expected_attempts=2)
        terminal["occurred_at"] = second["occurred_at"]
        accepted = client.post("/api/v1/events", json=[terminal, first], headers=cp.headers())
        assert accepted.status_code == 200, accepted.text
        old = _overview(client, org_id, cp.headers(org_id), group="model")
        old_as_of = old["freshness"]["as_of"]
        old_current = old["summary"]["current"]
        assert (
            old_current["logical_requests"],
            old_current["attempts"],
            old_current["known_cost_usd"],
            old_current["incomplete_requests"],
            old_current["cost_per_request_denominator"],
        ) == (1, 1, "0.000000000123", 1, 1)
        assert old["freshness"]["as_of"] == old_as_of
        assert old["freshness"]["delivery_completeness"] == "unavailable"

        accepted = client.post("/api/v1/events", json=[second], headers=cp.headers())
        assert accepted.status_code == 200, accepted.text
        latest = _overview(client, org_id, cp.headers(org_id), group="model")
        frozen = _overview(client, org_id, cp.headers(org_id), as_of=old_as_of, group="model")

        OverviewReportOut.model_validate(latest)
        assert latest["freshness"]["as_of"] != old_as_of
        assert latest["summary"]["current"]["logical_requests"] == 1
        assert latest["summary"]["current"]["attempts"] == 2
        assert latest["summary"]["current"]["known_cost_usd"] == "0.000000000444"
        assert latest["summary"]["current"]["incomplete_requests"] == 0
        assert latest["summary"]["current"]["token_sources"] == {
            "provider": 0,
            "estimated": 1,
            "partial": 1,
            "unavailable": 0,
            "not_applicable": 0,
        }
        assert latest["summary"]["current"]["cost_sources"] == {
            "catalog_estimate": 2,
            "unavailable": 0,
            "not_applicable": 0,
        }
        assert sum(point["metrics"]["attempts"] for point in latest["series"]) == 2
        assert sum(point["metrics"]["logical_requests"] for point in latest["series"]) == 1
        assert sum(Decimal(point["summary"]["current"]["known_cost_usd"]) for point in latest["attribution"]) == Decimal("0.000000000444")
        assert sum(point["summary"]["current"]["logical_requests"] for point in latest["attribution"]) == 1
        assert sum(point["summary"]["current"]["incomplete_requests"] for point in latest["attribution"]) == 0
        assert frozen["summary"] == old["summary"]

        filtered = _overview(client, org_id, cp.headers(org_id), model="gpt-test", split="model", group="model")
        assert filtered["summary"]["current"]["logical_requests"] == 1
        assert filtered["summary"]["current"]["attempts"] == 2
        assert filtered["summary"]["current"]["known_cost_usd"] == "0.000000000444"
        assert filtered["summary"]["current"]["incomplete_requests"] == 0
        assert sum(point["metrics"]["logical_requests"] for point in filtered["series"]) == 1
        assert sum(point["summary"]["current"]["logical_requests"] for point in filtered["attribution"]) == 1
        assert {point["id"] for point in filtered["attribution"]} == {"gpt-test", "fallback-model"}
        mismatched_attempt = _overview(client, org_id, cp.headers(org_id), model="gpt-test", provider="anthropic")
        assert mismatched_attempt["summary"]["current"]["logical_requests"] == 0


def test_overview_filters_attempt_facts_without_fabricating_unknown_accounting(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "overview-filters")
        workspace_id = make_workspace(client, cp.headers(org_id), "production")
        started_at = datetime.now(tz=UTC) - timedelta(hours=1)
        request_id = uuid7()
        principal_id = uuid7()
        unavailable = _attempt(
            RequestSeed(org_id, workspace_id, request_id, started_at, principal_id, key_id="key-special"),
            attempt_index=1,
            model="unknown-cost-model",
            provider="anthropic",
            cost=None,
        )
        terminal = _terminal(unavailable, expected_attempts=1, outcome="failed")
        assert client.post("/api/v1/events", json=[unavailable, terminal], headers=cp.headers()).status_code == 200

        report = _overview(
            client,
            org_id,
            cp.headers(org_id),
            workspace=str(workspace_id),
            principal=str(principal_id),
            inference_key="key-special",
            model="unknown-cost-model",
            provider="anthropic",
            split="provider",
            group="provider",
        )

        current = report["summary"]["current"]
        assert current["logical_requests"] == 1
        assert current["attempts"] == 1
        assert current["known_cost_usd"] == "0"
        assert current["known_input_tokens"] == 0
        assert current["unavailable_usage_attempts"] == 1
        assert current["unpriced_attempts"] == 1
        assert current["token_completeness"] == "unavailable"
        assert current["cost_completeness"] == "unavailable"
        assert current["cost_per_request_usd"] == "0.000000000000"
        assert report["attribution"][0]["label"] == "anthropic"


def test_provider_credential_attribution_assigns_retry_costs_and_requests_to_the_final_credential(  # noqa: PLR0915 integration scenario covers current, comparison, and unavailable accounting
    tmp_path,
):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "overview-credential-attribution")
        workspace_id = make_workspace(client, cp.headers(org_id), "production")
        today = datetime.now(tz=UTC).date()
        current_started = datetime.combine(today, datetime.min.time(), UTC) + timedelta(hours=1)
        comparison_started = current_started - timedelta(days=1)
        primary_id = uuid7()
        fallback_id = uuid7()
        unavailable_id = uuid7()
        prior_only_id = uuid7()

        comparison = _attempt(
            RequestSeed(org_id, workspace_id, uuid7(), comparison_started, uuid7()),
            attempt_index=1,
            cost="0.000000000001",
            credential_id=primary_id,
            credential_name="Old primary",
            credential_scope="org",
        )
        prior_only = _attempt(
            RequestSeed(org_id, workspace_id, uuid7(), comparison_started, uuid7()),
            attempt_index=1,
            cost="0.000000000005",
            credential_id=prior_only_id,
            credential_name="Prior only",
        )
        retry_seed = RequestSeed(org_id, workspace_id, uuid7(), current_started, uuid7())
        primary = _attempt(
            retry_seed,
            attempt_index=1,
            cost="0.000000000003",
            credential_id=primary_id,
            credential_name="Shared",
            credential_scope="org",
        )
        primary["cache_read_tokens"] = 2
        primary["cache_write_tokens"] = 1
        fallback = _attempt(
            retry_seed,
            attempt_index=2,
            cost="0.000000000007",
            credential_id=fallback_id,
            credential_name="Shared",
        )
        fallback["cache_read_tokens"] = 4
        fallback["cache_write_tokens"] = 3
        unavailable = _attempt(
            RequestSeed(org_id, workspace_id, uuid7(), current_started, uuid7()),
            attempt_index=1,
            cost=None,
            credential_id=unavailable_id,
            credential_name="Unavailable",
        )
        events = [
            comparison,
            _terminal(comparison, expected_attempts=1),
            prior_only,
            _terminal(prior_only, expected_attempts=1),
            primary,
            fallback,
            _terminal(fallback, expected_attempts=2),
            unavailable,
            _terminal(unavailable, expected_attempts=1, outcome="failed"),
        ]
        accepted = client.post("/api/v1/events", json=events, headers=cp.headers())
        assert accepted.status_code == 200, accepted.text

        report = _overview(
            client,
            org_id,
            cp.headers(org_id),
            range="custom",
            start_date=today.isoformat(),
            end_date=today.isoformat(),
            group="provider_credential",
        )

        assert [item["label"] for item in report["attribution"]] == [
            "workspace / Shared",
            "organization / Shared",
            "workspace / Prior only",
            "workspace / Unavailable",
        ]
        attribution = {item["id"]: item for item in report["attribution"]}
        primary_row = attribution[str(primary_id)]
        assert primary_row["label"] == "organization / Shared"
        assert primary_row["summary"]["current"]["known_cost_usd"] == "0.000000000003"
        assert primary_row["summary"]["comparison"]["known_cost_usd"] == "0.000000000001"
        assert primary_row["summary"]["delta"]["known_cost_usd"] == "0.000000000002"
        assert primary_row["summary"]["current"]["known_input_tokens"] == 10
        assert primary_row["summary"]["current"]["known_output_tokens"] == 5
        assert primary_row["summary"]["current"]["known_cache_read_tokens"] == 2
        assert primary_row["summary"]["current"]["known_cache_write_tokens"] == 1
        assert primary_row["summary"]["current"]["logical_requests"] == 0
        assert primary_row["summary"]["current"]["cost_per_request_usd"] is None
        assert primary_row["summary"]["current"]["cost_per_request_denominator"] == 0

        fallback_row = attribution[str(fallback_id)]
        assert fallback_row["label"] == "workspace / Shared"
        assert fallback_row["summary"]["current"]["known_cost_usd"] == "0.000000000007"
        assert fallback_row["summary"]["comparison"]["known_cost_usd"] == "0"
        assert fallback_row["summary"]["delta"]["known_cost_usd"] == "0.000000000007"
        assert fallback_row["summary"]["current"]["known_cache_read_tokens"] == 4
        assert fallback_row["summary"]["current"]["known_cache_write_tokens"] == 3
        assert fallback_row["summary"]["current"]["logical_requests"] == 1
        assert fallback_row["summary"]["current"]["cost_per_request_usd"] == "0.000000000007"
        assert fallback_row["summary"]["current"]["cost_per_request_denominator"] == 1

        unavailable_row = attribution[str(unavailable_id)]
        assert unavailable_row["summary"]["current"]["known_cost_usd"] == "0"
        assert unavailable_row["summary"]["delta"]["known_cost_usd"] == "0"
        assert unavailable_row["summary"]["current"]["known_input_tokens"] == 0
        assert unavailable_row["summary"]["current"]["known_output_tokens"] == 0
        assert unavailable_row["summary"]["current"]["logical_requests"] == 1
        assert unavailable_row["summary"]["current"]["cost_per_request_usd"] == "0.000000000000"
        assert unavailable_row["summary"]["current"]["cost_per_request_denominator"] == 1
        assert unavailable_row["summary"]["current"]["token_completeness"] == "unavailable"
        assert unavailable_row["summary"]["current"]["cost_completeness"] == "unavailable"

        prior_only_row = attribution[str(prior_only_id)]
        assert prior_only_row["summary"]["current"]["known_cost_usd"] == "0"
        assert prior_only_row["summary"]["comparison"]["known_cost_usd"] == "0.000000000005"
        assert prior_only_row["summary"]["delta"]["known_cost_usd"] == "-0.000000000005"
        assert sum(item["summary"]["current"]["logical_requests"] for item in report["attribution"]) == 2


def test_workspace_report_enforces_scope_and_rejects_a_workspace_filter(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        first_org = make_org(client, cp.headers(), "overview-first")
        first_workspace = make_workspace(client, cp.headers(first_org), "first")
        second_workspace = make_workspace(client, cp.headers(first_org), "second")
        second_org = make_org(client, cp.headers(), "overview-second")
        path = f"/api/v1/organizations/{first_org}/workspaces/{first_workspace}/reports/overview"
        query = {"range": "today", "timezone": "UTC"}

        allowed = client.get(path, params=query, headers=cp.headers(first_org, permissions=[Permission.usage_read]))
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["data"]["freshness"]["watermark"] is None
        assert client.get(path, params=query, headers=cp.headers(second_org, permissions=[Permission.usage_read])).status_code == 403
        workspace_headers = cp.headers(
            first_org,
            permissions=[Permission.usage_read],
            workspace_id=first_workspace,
        )
        assert client.get(path, params=query, headers=workspace_headers).status_code == 200
        sibling = f"/api/v1/organizations/{first_org}/workspaces/{second_workspace}/reports/overview"
        assert client.get(sibling, params=query, headers=workspace_headers).status_code == 403
        org_report = f"/api/v1/organizations/{first_org}/reports/overview"
        assert client.get(org_report, params=query, headers=workspace_headers).status_code == 403
        rejected = client.get(path, params={**query, "workspace": str(first_workspace)}, headers=cp.headers(first_org))
        assert rejected.status_code == 422


def test_pending_denial_is_unavailable_but_terminal_zero_attempt_denial_is_complete(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "overview-zero-attempts")
        workspace_id = make_workspace(client, cp.headers(org_id), "production")
        started_at = datetime.now(tz=UTC) - timedelta(hours=1)
        pending_attempt = _attempt(RequestSeed(org_id, workspace_id, uuid7(), started_at, uuid7(), "pending-key"), attempt_index=1)
        terminal_attempt = _attempt(RequestSeed(org_id, workspace_id, uuid7(), started_at, uuid7(), "denied-key"), attempt_index=1)
        terminal = _terminal(terminal_attempt, expected_attempts=0, outcome="denied")
        accepted = client.post(
            "/api/v1/events",
            json=[_denial(pending_attempt), _denial(terminal_attempt), terminal],
            headers=cp.headers(),
        )
        assert accepted.status_code == 200, accepted.text

        pending = _overview(client, org_id, cp.headers(org_id), inference_key="pending-key")["summary"]["current"]
        assert pending["attempts"] == 0
        assert pending["pending_requests"] == 1
        assert pending["incomplete_requests"] == 1
        assert pending["token_completeness"] == "unavailable"
        assert pending["cost_completeness"] == "unavailable"
        assert pending["token_sources"]["not_applicable"] == 1
        assert pending["cost_sources"]["not_applicable"] == 1

        denied = _overview(client, org_id, cp.headers(org_id), inference_key="denied-key")["summary"]["current"]
        assert denied["attempts"] == 0
        assert denied["outcomes"]["denied"] == 1
        assert denied["incomplete_requests"] == 0
        assert denied["token_completeness"] == "complete"
        assert denied["cost_completeness"] == "complete"


def test_cost_per_request_quantizes_exact_subcent_money_to_its_fixed_denominator(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "overview-subcent")
        workspace_id = make_workspace(client, cp.headers(org_id), "production")
        started_at = datetime.now(tz=UTC) - timedelta(hours=1)
        billed = _attempt(
            RequestSeed(org_id, workspace_id, uuid7(), started_at, uuid7(), "shared-key"),
            attempt_index=1,
            cost="0.000000000001",
        )
        first_denial = _attempt(RequestSeed(org_id, workspace_id, uuid7(), started_at, uuid7(), "shared-key"), attempt_index=1)
        second_denial = _attempt(RequestSeed(org_id, workspace_id, uuid7(), started_at, uuid7(), "shared-key"), attempt_index=1)
        events = [
            billed,
            _terminal(billed, expected_attempts=1),
            _denial(first_denial),
            _terminal(first_denial, expected_attempts=0, outcome="denied"),
            _denial(second_denial),
            _terminal(second_denial, expected_attempts=0, outcome="denied"),
        ]
        accepted = client.post("/api/v1/events", json=events, headers=cp.headers())
        assert accepted.status_code == 200, accepted.text

        current = _overview(client, org_id, cp.headers(org_id), inference_key="shared-key")["summary"]["current"]
        assert current["known_cost_usd"] == "0.000000000001"
        assert current["cost_per_request_denominator"] == 3
        assert current["cost_per_request_usd"] == "0.000000000000"


def test_overview_uses_immutable_snapshot_labels_after_resources_are_deleted(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "overview-snapshots")
        workspace_id = make_workspace(client, cp.headers(org_id), "production")
        attempt = _attempt(
            RequestSeed(org_id, workspace_id, uuid7(), datetime.now(tz=UTC) - timedelta(hours=1), uuid7()),
            attempt_index=1,
        )
        assert client.post("/api/v1/events", json=[attempt, _terminal(attempt, expected_attempts=1)], headers=cp.headers()).status_code == 200
        deleted = client.delete(f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}", headers=cp.headers(org_id))
        assert deleted.status_code == 200, deleted.text

        report = _overview(client, org_id, cp.headers(org_id), group="workspace")

        assert report["attribution"][0]["id"] == str(workspace_id)
        assert report["attribution"][0]["label"] == "Production"


def test_unknown_watermark_and_oversized_filter_sets_are_rejected(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "overview-invalid-cutoff")
        path = f"/api/v1/organizations/{org_id}/reports/overview"
        base = [("range", "today"), ("timezone", "UTC")]

        unknown = client.get(path, params=[*base, ("as_of", str(uuid7()))], headers=cp.headers(org_id))
        assert unknown.status_code == 422
        oversized = client.get(
            path,
            params=[*base, *(("model", f"model-{index}") for index in range(51))],
            headers=cp.headers(org_id),
        )
        assert oversized.status_code == 422


def test_custom_current_comparison_and_delta_use_request_start_membership(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "overview-comparison")
        workspace_id = make_workspace(client, cp.headers(org_id), "production")
        today = datetime.now(tz=UTC).date()
        current_started = datetime.combine(today, datetime.min.time(), UTC) + timedelta(hours=1)
        comparison_started = current_started - timedelta(days=1)
        current = _attempt(
            RequestSeed(org_id, workspace_id, uuid7(), current_started, uuid7()),
            attempt_index=1,
            cost="0.000000000003",
        )
        comparison = _attempt(
            RequestSeed(org_id, workspace_id, uuid7(), comparison_started, uuid7()),
            attempt_index=1,
            cost="0.000000000001",
        )
        accepted = client.post(
            "/api/v1/events",
            json=[current, _terminal(current, expected_attempts=1), comparison, _terminal(comparison, expected_attempts=1)],
            headers=cp.headers(),
        )
        assert accepted.status_code == 200, accepted.text

        report = _overview(
            client,
            org_id,
            cp.headers(org_id),
            range="custom",
            start_date=today.isoformat(),
            end_date=today.isoformat(),
        )

        assert report["summary"]["current"]["known_cost_usd"] == "0.000000000003"
        assert report["summary"]["comparison"]["known_cost_usd"] == "0.000000000001"
        assert report["summary"]["delta"]["known_cost_usd"] == "0.000000000002"
        current_start = datetime.fromisoformat(report["periods"]["current"]["start_at"])
        assert current_start == datetime.combine(today, datetime.min.time(), UTC)
        assert report["periods"]["comparison"]["end_at"] == report["periods"]["current"]["start_at"]


def test_report_snapshot_keeps_latest_period_after_batch_metadata_changes(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "overview-period-anchor")
        workspace_id = make_workspace(client, cp.headers(org_id), "production")
        today_start = datetime.combine(datetime.now(tz=UTC).date(), datetime.min.time(), UTC)
        yesterday_request = datetime.now(tz=UTC) - timedelta(hours=1)
        yesterday_receipt = today_start - timedelta(hours=12)
        attempt = _attempt(RequestSeed(org_id, workspace_id, uuid7(), yesterday_request, uuid7()), attempt_index=1)
        accepted = client.post("/api/v1/events", json=[attempt, _terminal(attempt, expected_attempts=1)], headers=cp.headers())
        assert accepted.status_code == 200, accepted.text
        latest = _overview(client, org_id, cp.headers(org_id), range="today")
        as_of = latest["freshness"]["as_of"]

        async def age_batch() -> None:
            batches = await UsageIngestBatch.find()
            batch = max(batches, key=lambda item: item.ingest_id or 0)
            batch.received_at = yesterday_receipt
            await batch.save()

        run_in_db(tmp_path, age_batch)

        frozen = _overview(client, org_id, cp.headers(org_id), range="today", as_of=as_of)

        assert latest["summary"]["current"]["logical_requests"] == 1
        assert frozen["summary"]["current"]["logical_requests"] == 1
        assert latest["periods"] == frozen["periods"]
        assert frozen["freshness"]["as_of"] == as_of


def test_report_query_validation_is_exposed_by_both_routes(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "overview-validation")
        workspace_id = make_workspace(client, cp.headers(org_id), "production")
        paths = [
            f"/api/v1/organizations/{org_id}/reports/overview",
            f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/reports/overview",
        ]
        invalid_queries = [
            {"range": "custom", "timezone": "UTC"},
            {"range": "7d", "timezone": "UTC", "start_date": "2026-01-01"},
            {"range": "custom", "timezone": "UTC", "start_date": "2026-01-02", "end_date": "2026-01-01"},
            {"range": "today", "timezone": "Not/AZone"},
        ]

        for path in paths:
            for query in invalid_queries:
                assert client.get(path, params=query, headers=cp.headers(org_id)).status_code == 422
