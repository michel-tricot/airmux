from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient
from helpers import make_org, make_workspace, run_in_db, setup_control_plane

from api_models import GatewayRequestCsvExportOut, GatewayRequestDetailOut, GatewayRequestPageOut
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
    authentication_label: str = "Production key"
    principal_label: str = "Checkout service"
    workspace_label: str = "Production"
    bundle_id: UUID = field(default_factory=uuid7)


def _attempt(  # noqa: PLR0913 event fixture exposes independent accounting dimensions
    seed: RequestSeed,
    attempt_index: int,
    *,
    model: str = "gpt-test",
    provider: str = "openai",
    source: str = "provider",
    cost: str = "0.000000000123",
    status: str = "ok",
    credential_name: str = "default",
) -> dict:
    unavailable = source == "unavailable"
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
        "authentication_label": seed.authentication_label,
        "user_id": str(seed.user_id),
        "principal_label": seed.principal_label,
        "principal_type": "service_account",
        "workspace_label": seed.workspace_label,
        "requested_model_id": "requested-model",
        "requested_capabilities": [],
        "model_id": model,
        "provider_id": provider,
        "bundle_id": str(seed.bundle_id),
        "input_tokens": None if unavailable else 10,
        "output_tokens": None if unavailable else 5,
        "token_usage_source": source,
        "attempt_index": attempt_index,
        "max_output_tokens": 128,
        "input_price_per_mtok": "1",
        "output_price_per_mtok": "2",
        "cache_read_price_per_mtok": "0.1",
        "cache_write_price_per_mtok": "1.25",
        "cost_source": "unavailable" if unavailable else "catalog_estimate",
        "cost_usd": None if unavailable else cost,
        "cost_input_usd": None if unavailable else cost,
        "cost_output_usd": None if unavailable else "0",
        "cache_read_tokens": None if unavailable else 2,
        "cache_write_tokens": None if unavailable else 1,
        "latency_ms": 40 + attempt_index,
        "status": status,
        "stream": False,
        "credential_id": str(uuid7()),
        "credential_scope": "workspace",
        "credential_name": credential_name,
    }


def _terminal(attempt: dict, expected_attempts: int, *, outcome: str = "succeeded", latency_ms: int = 100) -> dict:
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
        "latency_ms": latency_ms,
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


def _query(**overrides: str | int) -> dict[str, str | int]:
    return {"range": "7d", "timezone": "UTC", **overrides}


def _org_path(org_id: UUID, suffix: str = "") -> str:
    return f"/api/v1/organizations/{org_id}/reports/requests{suffix}"


def test_request_report_reconciles_ordered_retries_under_a_stable_watermark(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "requests-retries")
        workspace_id = make_workspace(client, cp.headers(org_id), "production")
        seed = RequestSeed(org_id, workspace_id, uuid7(), datetime.now(tz=UTC) - timedelta(hours=1), uuid7())
        first = _attempt(seed, 1, source="estimated", status="upstream_error")
        second = _attempt(seed, 2, model="fallback-model", provider="anthropic", source="partial", cost="0.000000000321")
        terminal = _terminal(second, 2)

        accepted = client.post("/api/v1/events", json=[terminal, second], headers=cp.headers())
        assert accepted.status_code == 200, accepted.text
        old_response = client.get(_org_path(org_id), params=_query(), headers=cp.headers(org_id))
        assert old_response.status_code == 200, old_response.text
        old_as_of = old_response.json()["data"]["freshness"]["as_of"]
        old = GatewayRequestPageOut.model_validate(old_response.json()["data"])
        assert len(old.items) == 1
        assert [attempt.root.attempt_index for attempt in old.items[0].attempts] == [2]
        assert old.items[0].evidence_complete is False
        assert old.items[0].confidence == "partial"
        assert old.items[0].known_cost_usd == "0.000000000321"

        accepted = client.post("/api/v1/events", json=[first], headers=cp.headers())
        assert accepted.status_code == 200, accepted.text
        latest = client.get(_org_path(org_id), params=_query(), headers=cp.headers(org_id)).json()["data"]
        frozen = client.get(_org_path(org_id), params=_query(as_of=old_as_of), headers=cp.headers(org_id)).json()["data"]

        assert [attempt["attempt_index"] for attempt in latest["items"][0]["attempts"]] == [1, 2]
        assert latest["items"][0]["evidence_complete"] is True
        assert latest["items"][0]["known_cost_usd"] == "0.000000000444"
        assert [attempt["attempt_index"] for attempt in frozen["items"][0]["attempts"]] == [2]
        assert frozen["freshness"]["as_of"] == old_as_of

        filtered = client.get(
            _org_path(org_id),
            params=_query(model="gpt-test", provider="openai"),
            headers=cp.headers(org_id),
        ).json()["data"]
        assert len(filtered["items"]) == 1
        assert [attempt["attempt_index"] for attempt in filtered["items"][0]["attempts"]] == [1, 2]
        mismatched = client.get(
            _org_path(org_id),
            params=_query(model="gpt-test", provider="anthropic"),
            headers=cp.headers(org_id),
        ).json()["data"]
        assert mismatched["items"] == []
        overview = client.get(
            f"/api/v1/organizations/{org_id}/reports/overview",
            params={"range": "7d", "timezone": "UTC", "model": "gpt-test", "provider": "openai"},
            headers=cp.headers(org_id),
        ).json()["data"]
        assert overview["summary"]["current"]["attempts"] == 2
        assert overview["summary"]["current"]["known_cost_usd"] == filtered["items"][0]["known_cost_usd"]
        partial = client.get(
            _org_path(org_id),
            params=_query(outcome="succeeded", confidence="partial"),
            headers=cp.headers(org_id),
        ).json()["data"]
        assert [item["request_id"] for item in partial["items"]] == [str(seed.request_id)]
        assert (
            client.get(
                _org_path(org_id),
                params=_query(outcome="pending"),
                headers=cp.headers(org_id),
            ).json()["data"]["items"]
            == []
        )


def test_request_report_keysets_every_sort_and_direction_without_skips(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "requests-keysets")
        workspace_id = make_workspace(client, cp.headers(org_id), "production")
        started_at = datetime.now(tz=UTC) - timedelta(hours=1)
        events = []
        for index in range(4):
            seed = RequestSeed(org_id, workspace_id, uuid7(), started_at + timedelta(seconds=index // 2), uuid7(), key_id=f"key-{index}")
            attempt = _attempt(seed, 1, cost="0.000000000123" if index < 2 else "0.000000000999")
            events.extend((attempt, _terminal(attempt, 1, latency_ms=100 if index < 2 else 200)))
        pending_seed = RequestSeed(org_id, workspace_id, uuid7(), started_at + timedelta(seconds=3), uuid7(), key_id="key-pending")
        events.append(_attempt(pending_seed, 1))
        assert client.post("/api/v1/events", json=list(reversed(events)), headers=cp.headers()).status_code == 200

        pending = client.get(
            _org_path(org_id),
            params=_query(outcome="pending", confidence="partial"),
            headers=cp.headers(org_id),
        ).json()["data"]["items"]
        assert [item["request_id"] for item in pending] == [str(pending_seed.request_id)]
        assert pending[0]["evidence_complete"] is False

        for sort in ("request_started_at", "latency_ms", "known_cost_usd", "known_tokens"):
            for direction in ("asc", "desc"):
                whole = client.get(_org_path(org_id), params=_query(sort=sort, direction=direction, limit=200), headers=cp.headers(org_id)).json()[
                    "data"
                ]
                expected = [item["request_id"] for item in whole["items"]]
                actual: list[str] = []
                cursor = None
                while True:
                    params = _query(sort=sort, direction=direction, limit=1)
                    if cursor is not None:
                        params["cursor"] = cursor
                    page = client.get(_org_path(org_id), params=params, headers=cp.headers(org_id))
                    assert page.status_code == 200, page.text
                    body = page.json()["data"]
                    actual.extend(item["request_id"] for item in body["items"])
                    cursor = body["page"]["next_cursor"]
                    if cursor is None:
                        break
                assert actual == expected
                assert len(actual) == len(set(actual)) == 5
                if sort == "latency_ms":
                    assert actual[-1] == str(pending_seed.request_id)


def test_request_report_cursor_is_bound_to_filter_scope_and_watermark(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "requests-cursor")
        first_workspace = make_workspace(client, cp.headers(org_id), "first")
        second_workspace = make_workspace(client, cp.headers(org_id), "second")
        events = []
        for workspace_id, key_id in ((first_workspace, "one"), (second_workspace, "two")):
            seed = RequestSeed(org_id, workspace_id, uuid7(), datetime.now(tz=UTC) - timedelta(minutes=1), uuid7(), key_id=key_id)
            attempt = _attempt(seed, 1)
            events.extend((attempt, _terminal(attempt, 1)))
        assert client.post("/api/v1/events", json=events, headers=cp.headers()).status_code == 200

        first = client.get(_org_path(org_id), params=_query(limit=1), headers=cp.headers(org_id)).json()["data"]
        cursor = first["page"]["next_cursor"]
        assert cursor
        assert client.get(_org_path(org_id), params=_query(limit=1, cursor=cursor), headers=cp.headers(org_id)).status_code == 200
        changed = client.get(_org_path(org_id), params=_query(limit=1, cursor=cursor, inference_key="one"), headers=cp.headers(org_id))
        assert changed.status_code == 422
        assert changed.json() == {"detail": "invalid cursor"}
        tampered = cursor[:-1] + ("A" if cursor[-1] != "A" else "B")
        assert client.get(_org_path(org_id), params=_query(cursor=tampered), headers=cp.headers(org_id)).status_code == 422

        workspace_path = f"/api/v1/organizations/{org_id}/workspaces/{first_workspace}/reports/requests"
        scoped = client.get(workspace_path, params=_query(cursor=cursor), headers=cp.headers(org_id))
        assert scoped.status_code == 422


def test_request_report_detail_search_snapshots_and_usage_read_isolation(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "requests-detail")
        first_workspace = make_workspace(client, cp.headers(org_id), "first")
        second_workspace = make_workspace(client, cp.headers(org_id), "second")
        seed = RequestSeed(
            org_id,
            first_workspace,
            uuid7(),
            datetime.now(tz=UTC) - timedelta(minutes=1),
            uuid7(),
            authentication_label="=Finance%_key",
            principal_label="Zoë\nOps",
            workspace_label="Original workspace",
        )
        attempt = _attempt(seed, 1, credential_name="@billing")
        decoy_seed = RequestSeed(
            org_id,
            first_workspace,
            uuid7(),
            seed.started_at - timedelta(seconds=1),
            uuid7(),
            authentication_label="FinanceABkey",
        )
        decoy = _attempt(decoy_seed, 1)
        accepted = client.post("/api/v1/events", json=[attempt, _terminal(attempt, 1), decoy, _terminal(decoy, 1)], headers=cp.headers())
        assert accepted.status_code == 200
        as_of = client.get(_org_path(org_id), params=_query(), headers=cp.headers(org_id)).json()["data"]["freshness"]["as_of"]

        for search in ("%_", "Zoë", "@billing"):
            found = client.get(_org_path(org_id), params=_query(search=search), headers=cp.headers(org_id)).json()["data"]["items"]
            assert [item["request_id"] for item in found] == [str(seed.request_id)]

        detail_path = _org_path(org_id, f"/{seed.request_id}")
        detail = client.get(detail_path, params={"as_of": as_of}, headers=cp.headers(org_id))
        assert detail.status_code == 200, detail.text
        parsed = GatewayRequestDetailOut.model_validate(detail.json()["data"])
        assert parsed.request.workspace_label == "Original workspace"
        assert parsed.request.attempts[0].root.credential_name == "@billing"

        wrong_org = make_org(client, cp.headers(), "requests-wrong-org")
        assert client.get(_org_path(wrong_org, f"/{seed.request_id}"), headers=cp.headers(wrong_org)).status_code == 404
        wrong_workspace_path = f"/api/v1/organizations/{org_id}/workspaces/{second_workspace}/reports/requests/{seed.request_id}"
        assert client.get(wrong_workspace_path, headers=cp.headers(org_id)).status_code == 404

        workspace_key = cp.headers(org_id, workspace_id=first_workspace, permissions=[Permission.usage_read])
        workspace_path = f"/api/v1/organizations/{org_id}/workspaces/{first_workspace}/reports/requests/{seed.request_id}"
        assert client.get(workspace_path, headers=workspace_key).status_code == 200
        sibling_path = f"/api/v1/organizations/{org_id}/workspaces/{second_workspace}/reports/requests"
        assert client.get(sibling_path, params=_query(), headers=workspace_key).status_code == 403
        assert client.get(_org_path(org_id), params=_query(), headers=workspace_key).status_code == 403

        deleted = client.delete(f"/api/v1/organizations/{org_id}/workspaces/{first_workspace}", headers=cp.headers(org_id))
        assert deleted.status_code == 200, deleted.text
        retained = client.get(detail_path, headers=cp.headers(org_id))
        assert retained.status_code == 200, retained.text
        assert retained.json()["data"]["request"]["workspace_label"] == "Original workspace"


def test_request_report_preserves_denial_evidence_and_hides_later_requests_at_cutoff(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "requests-denial")
        workspace_id = make_workspace(client, cp.headers(org_id), "production")
        denied_seed = RequestSeed(org_id, workspace_id, uuid7(), datetime.now(tz=UTC) - timedelta(minutes=2), uuid7())
        denied_attempt = _attempt(denied_seed, 1)
        denial = _denial(denied_attempt)
        denied_terminal = _terminal(denial, 0, outcome="denied")
        early = client.post("/api/v1/events", json=[denial, denied_terminal], headers=cp.headers())
        assert early.status_code == 200, early.text
        early_as_of = client.get(_org_path(org_id), params=_query(), headers=cp.headers(org_id)).json()["data"]["freshness"]["as_of"]

        later_seed = RequestSeed(org_id, workspace_id, uuid7(), datetime.now(tz=UTC) - timedelta(minutes=1), uuid7())
        later_attempt = _attempt(later_seed, 1)
        later = client.post("/api/v1/events", json=[later_attempt, _terminal(later_attempt, 1)], headers=cp.headers())
        assert later.status_code == 200, later.text

        listed = client.get(
            _org_path(org_id),
            params=_query(outcome="denied", confidence="not_applicable"),
            headers=cp.headers(org_id),
        )
        assert listed.status_code == 200, listed.text
        item = listed.json()["data"]["items"][0]
        assert item["request_id"] == str(denied_seed.request_id)
        assert item["attempts"] == []
        assert item["denial"]["status"] == "denied"
        assert item["known_cost_usd"] == "0"

        denied_detail = client.get(_org_path(org_id, f"/{denied_seed.request_id}"), headers=cp.headers(org_id))
        assert denied_detail.status_code == 200, denied_detail.text
        assert denied_detail.json()["data"]["request"]["denial"]["event_id"] == denial["event_id"]

        later_at_early_cutoff = client.get(
            _org_path(org_id, f"/{later_seed.request_id}"),
            params={"as_of": early_as_of},
            headers=cp.headers(org_id),
        )
        assert later_at_early_cutoff.status_code == 404

        export = client.get(
            f"/api/v1/organizations/{org_id}/reports/request-export",
            params=_query(outcome="denied"),
            headers=cp.headers(org_id),
        )
        assert export.status_code == 200, export.text
        row = next(csv.DictReader(io.StringIO(export.json()["data"]["csv"])))
        assert json.loads(row["denial_json"])["event_id"] == denial["event_id"]


def test_request_report_snapshot_keeps_latest_period_after_batch_metadata_changes(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "requests-period-anchor")
        workspace_id = make_workspace(client, cp.headers(org_id), "production")
        today_start = datetime.combine(datetime.now(tz=UTC).date(), datetime.min.time(), UTC)
        yesterday_receipt = today_start - timedelta(hours=12)
        seed = RequestSeed(org_id, workspace_id, uuid7(), datetime.now(tz=UTC) - timedelta(minutes=2), uuid7())
        matching_attempt = _attempt(seed, 1, status="upstream_error")
        fallback_attempt = _attempt(seed, 2, model="fallback-model", provider="anthropic", cost="0.000000000321")
        accepted = client.post(
            "/api/v1/events",
            json=[matching_attempt, fallback_attempt, _terminal(fallback_attempt, 2)],
            headers=cp.headers(),
        )
        assert accepted.status_code == 200, accepted.text
        latest = client.get(_org_path(org_id), params=_query(range="today"), headers=cp.headers(org_id)).json()["data"]
        as_of = latest["freshness"]["as_of"]

        async def age_batch() -> None:
            batches = await UsageIngestBatch.find()
            batch = max(batches, key=lambda item: item.ingest_id or 0)
            batch.received_at = yesterday_receipt
            await batch.save()

        run_in_db(tmp_path, age_batch)

        later_seed = RequestSeed(org_id, workspace_id, uuid7(), datetime.now(tz=UTC) - timedelta(minutes=1), uuid7())
        later_attempt = _attempt(later_seed, 1)
        assert client.post("/api/v1/events", json=[later_attempt, _terminal(later_attempt, 1)], headers=cp.headers()).status_code == 200

        frozen = client.get(
            _org_path(org_id),
            params=_query(range="today", as_of=as_of, model="gpt-test", provider="openai"),
            headers=cp.headers(org_id),
        ).json()["data"]

        assert [item["request_id"] for item in latest["items"]] == [str(seed.request_id)]
        assert frozen["items"] == latest["items"]
        assert [attempt["attempt_index"] for attempt in frozen["items"][0]["attempts"]] == [1, 2]
        assert frozen["period"] == latest["period"]
        assert frozen["freshness"]["as_of"] == as_of
        overview = client.get(
            f"/api/v1/organizations/{org_id}/reports/overview",
            params={"range": "today", "timezone": "UTC", "as_of": as_of, "model": "gpt-test", "provider": "openai"},
            headers=cp.headers(org_id),
        ).json()["data"]
        detail = client.get(_org_path(org_id, f"/{seed.request_id}"), params={"as_of": as_of}, headers=cp.headers(org_id))
        exported = client.get(
            f"/api/v1/organizations/{org_id}/reports/request-export",
            params=_query(range="today", as_of=as_of, model="gpt-test", provider="openai"),
            headers=cp.headers(org_id),
        ).json()["data"]
        assert overview["summary"]["current"]["logical_requests"] == 1
        assert overview["freshness"]["as_of"] == as_of
        assert detail.status_code == 200
        assert detail.json()["data"]["freshness"]["as_of"] == as_of
        assert exported["row_count"] == 1
        assert exported["period"] == latest["period"]
        assert exported["freshness"]["as_of"] == as_of
        listed_cost = sum(Decimal(item["known_cost_usd"]) for item in frozen["items"])
        detail_cost = Decimal(detail.json()["data"]["request"]["known_cost_usd"])
        csv_cost = Decimal(next(csv.DictReader(io.StringIO(exported["csv"])))["known_cost_usd"])
        assert overview["summary"]["current"]["logical_requests"] == len(frozen["items"]) == 1
        assert listed_cost == Decimal("0.000000000444")
        assert Decimal(overview["summary"]["current"]["known_cost_usd"]) == listed_cost == detail_cost == csv_cost


def test_request_report_freshness_is_scope_local_and_snapshot_tokens_do_not_cross_scopes(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        active_org = make_org(client, cp.headers(), "requests-active-org")
        active_workspace = make_workspace(client, cp.headers(active_org), "active")
        empty_org = make_org(client, cp.headers(), "requests-empty-org")
        empty_workspace = make_workspace(client, cp.headers(empty_org), "empty")
        seed = RequestSeed(active_org, active_workspace, uuid7(), datetime.now(tz=UTC) - timedelta(minutes=1), uuid7())
        attempt = _attempt(seed, 1)
        assert client.post("/api/v1/events", json=[attempt, _terminal(attempt, 1)], headers=cp.headers()).status_code == 200

        active = client.get(_org_path(active_org), params=_query(), headers=cp.headers(active_org)).json()["data"]
        empty = client.get(_org_path(empty_org), params=_query(), headers=cp.headers(empty_org)).json()["data"]
        empty_workspace_path = f"/api/v1/organizations/{empty_org}/workspaces/{empty_workspace}/reports/requests"
        empty_workspace_report = client.get(empty_workspace_path, params=_query(), headers=cp.headers(empty_org)).json()["data"]

        assert active["freshness"]["watermark"] is not None
        assert empty["freshness"]["watermark"] is None
        assert empty_workspace_report["freshness"]["watermark"] is None
        later_seed = RequestSeed(active_org, active_workspace, uuid7(), datetime.now(tz=UTC) - timedelta(seconds=30), uuid7())
        later_attempt = _attempt(later_seed, 1)
        assert client.post("/api/v1/events", json=[later_attempt, _terminal(later_attempt, 1)], headers=cp.headers()).status_code == 200
        frozen_empty = client.get(
            _org_path(empty_org),
            params=_query(as_of=empty["freshness"]["as_of"]),
            headers=cp.headers(empty_org),
        ).json()["data"]
        assert frozen_empty["items"] == []
        assert frozen_empty["freshness"]["as_of"] == empty["freshness"]["as_of"]
        empty_overview = client.get(
            f"/api/v1/organizations/{empty_org}/reports/overview",
            params={"range": "7d", "timezone": "UTC"},
            headers=cp.headers(empty_org),
        ).json()["data"]
        assert empty_overview["freshness"]["watermark"] is None
        assert empty_overview["freshness"]["received_at"] is None
        rejected = client.get(
            _org_path(empty_org),
            params=_query(as_of=active["freshness"]["as_of"]),
            headers=cp.headers(empty_org),
        )
        assert rejected.status_code == 422
        overview_rejected = client.get(
            f"/api/v1/organizations/{empty_org}/reports/overview",
            params={"range": "7d", "timezone": "UTC", "as_of": active["freshness"]["as_of"]},
            headers=cp.headers(empty_org),
        )
        assert overview_rejected.status_code == 422

        terminal_org = make_org(client, cp.headers(), "requests-terminal-only")
        terminal_workspace = make_workspace(client, cp.headers(terminal_org), "terminal")
        terminal_seed = RequestSeed(terminal_org, terminal_workspace, uuid7(), datetime.now(tz=UTC) - timedelta(minutes=1), uuid7())
        terminal_attempt = _attempt(terminal_seed, 1)
        assert client.post("/api/v1/events", json=[_terminal(terminal_attempt, 1, outcome="failed")], headers=cp.headers()).status_code == 200
        terminal_only = client.get(_org_path(terminal_org), params=_query(), headers=cp.headers(terminal_org)).json()["data"]
        assert terminal_only["freshness"]["watermark"] is not None
        assert terminal_only["items"][0]["attempts"] == []


def test_request_export_is_full_lossless_safe_and_bounded(tmp_path, monkeypatch):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "requests-export")
        workspace_id = make_workspace(client, cp.headers(org_id), "production")
        events = []
        for index in range(3):
            seed = RequestSeed(
                org_id,
                workspace_id,
                uuid7(),
                datetime.now(tz=UTC) - timedelta(minutes=index + 1),
                uuid7(),
                key_id=f"key-{index}",
                principal_label="=SUM(A1:A2)" if index == 0 else "Zoë\nOps",
            )
            attempt = _attempt(seed, 1, source="unavailable" if index == 2 else "provider")
            events.extend((attempt, _terminal(attempt, 1)))
        assert client.post("/api/v1/events", json=events, headers=cp.headers()).status_code == 200

        path = f"/api/v1/organizations/{org_id}/reports/request-export"
        page = client.get(_org_path(org_id), params=_query(limit=1), headers=cp.headers(org_id)).json()["data"]
        assert len(page["items"]) == 1
        assert page["page"]["next_cursor"] is not None
        response = client.get(path, params=_query(sort="request_started_at", direction="asc"), headers=cp.headers(org_id))
        assert response.status_code == 200, response.text
        export = GatewayRequestCsvExportOut.model_validate(response.json()["data"])
        assert export.content_type == "text/csv; charset=utf-8"
        assert export.row_count == 3
        rows = list(csv.DictReader(io.StringIO(export.csv)))
        assert len(rows) == 3
        assert rows[0]["request_started_at"] <= rows[1]["request_started_at"] <= rows[2]["request_started_at"]
        injected = next(row for row in rows if "SUM" in row["principal_label"])
        assert injected["principal_label"].startswith("'")
        newline = next(row for row in rows if "Zoë" in row["principal_label"])
        assert newline["principal_label"] == "Zoë\nOps"
        attempts = json.loads(rows[0]["attempts_json"])
        assert [attempt["attempt_index"] for attempt in attempts] == [1]
        unavailable = next(row for row in rows if row["token_completeness"] == "unavailable")
        assert unavailable["known_cost_usd"] == "0"
        assert json.loads(unavailable["attempts_json"])[0]["cost_usd"] is None

        monkeypatch.setattr("control_plane.models.request_report.MAX_EXPORT_ROWS", 2)
        too_many = client.get(path, params=_query(), headers=cp.headers(org_id))
        assert too_many.status_code == 413
        assert "narrow the filters" in too_many.json()["detail"]
        monkeypatch.setattr("control_plane.models.request_report.MAX_EXPORT_ROWS", 100_000)
        monkeypatch.setattr("control_plane.models.request_report.MAX_EXPORT_EVIDENCE", 2)
        too_much_evidence = client.get(path, params=_query(), headers=cp.headers(org_id))
        assert too_much_evidence.status_code == 413
        monkeypatch.setattr("control_plane.models.request_report.MAX_EXPORT_EVIDENCE", 500_000)
        monkeypatch.setattr("control_plane.models.request_report.MAX_EXPORT_BYTES", 100)
        too_large = client.get(path, params=_query(), headers=cp.headers(org_id))
        assert too_large.status_code == 413
