from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import StringIO
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from helpers import make_org, make_user, make_workspace, setup_control_plane

from contract import uuid7
from control_plane.authz import Permission


def _event(org_id: UUID, workspace_id: UUID, *, request_id: UUID | None = None, started_at: datetime | None = None) -> dict:
    started_at = started_at or datetime.now(UTC) - timedelta(minutes=1)
    return {
        "event_id": str(uuid7()),
        "request_id": str(request_id or uuid7()),
        "request_started_at": started_at.isoformat(),
        "attempt_started_at": started_at.isoformat(),
        "occurred_at": started_at.isoformat(),
        "org_id": str(org_id),
        "workspace_id": str(workspace_id),
        "key_id": "key",
        "request_source": "inference_key",
        "user_id": str(uuid7()),
        "requested_model_id": "gpt-test",
        "requested_capabilities": [],
        "model_id": "gpt-test",
        "provider_id": "openai",
        "bundle_id": str(uuid4()),
        "input_tokens": 4,
        "output_tokens": 0,
        "token_usage_source": "provider",
        "max_output_tokens": 128,
        "cost_usd": "0.000002",
        "cost_input_usd": "0.000002",
        "latency_ms": 100,
        "status": "upstream_error",
        "stream": False,
        "credential_id": str(uuid7()),
        "credential_scope": "workspace",
    }


def test_reports_use_one_path_for_org_and_authorized_workspace_scope(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        org_id = make_org(client, root)
        org_headers = cp.headers(org_id)
        first = make_workspace(client, org_headers, "first")
        second = make_workspace(client, org_headers, "second")
        events = [_event(org_id, first), _event(org_id, second)]
        assert client.post("/api/v1/events", json=events, headers=root).json()["data"]["ingested"] == 2

        path = f"/api/v1/organizations/{org_id}/reports"
        assert client.get(f"{path}/usage", headers=org_headers).json()["data"]["totals"]["requests"] == 2
        scoped = client.get(f"{path}/usage", params={"workspace_id": str(first)}, headers=org_headers)
        assert scoped.status_code == 200, scoped.text
        assert scoped.json()["data"]["totals"]["requests"] == 1
        assert client.get(f"{path}/requests", params={"workspace_id": str(first)}, headers=org_headers).status_code == 200
        assert client.get(f"{path}/attribution", params={"workspace_id": str(first), "group_by": "provider"}, headers=org_headers).status_code == 200

        viewer = make_user(tmp_path, "report-viewer@example.com")
        assert client.put(f"/api/v1/organizations/{org_id}/users/{viewer.id}", json={"role": "member"}, headers=org_headers).status_code == 200
        assert (
            client.put(
                f"/api/v1/organizations/{org_id}/workspaces/{first}/members/{viewer.id}",
                json={"role": "viewer"},
                headers=org_headers,
            ).status_code
            == 200
        )
        workspace_headers = cp.headers_for(org_id, viewer.id, first, permissions=frozenset({Permission.usage_read}))
        assert client.get(f"{path}/usage", headers=workspace_headers).status_code == 403
        allowed = client.get(f"{path}/usage", params={"workspace_id": str(first)}, headers=workspace_headers)
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["data"]["totals"]["requests"] == 1
        assert client.get(f"{path}/usage", params={"workspace_id": str(second)}, headers=workspace_headers).status_code == 403
        assert client.get(f"{path}/requests", params={"workspace_id": str(second)}, headers=workspace_headers).status_code == 403


def test_provider_filter_counts_matching_cost_and_detail_keeps_all_attempts(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        org_id = make_org(client, root)
        workspace_id = make_workspace(client, cp.headers(org_id))
        request_id = uuid7()
        first = _event(org_id, workspace_id, request_id=request_id)
        second = {
            **first,
            "event_id": str(uuid7()),
            "provider_id": "anthropic",
            "attempt_started_at": (datetime.fromisoformat(first["attempt_started_at"]) + timedelta(seconds=1)).isoformat(),
            "occurred_at": (datetime.fromisoformat(first["occurred_at"]) + timedelta(seconds=1)).isoformat(),
            "status": "ok",
            "input_tokens": 6,
            "output_tokens": 3,
            "cost_usd": "0.000003",
            "cost_input_usd": "0.000003",
        }
        assert client.post("/api/v1/events", json=[second, first], headers=root).json()["data"]["ingested"] == 2
        path = f"/api/v1/organizations/{org_id}/reports"
        headers = cp.headers(org_id)

        all_usage = client.get(f"{path}/usage", headers=headers)
        assert all_usage.status_code == 200, all_usage.text
        assert all_usage.json()["data"]["totals"]["requests"] == 1
        assert Decimal(all_usage.json()["data"]["totals"]["cost_usd"]) == Decimal("0.000005")

        filtered = client.get(f"{path}/usage", params={"provider_id": "anthropic"}, headers=headers)
        assert filtered.status_code == 200, filtered.text
        assert filtered.json()["data"]["totals"]["requests"] == 1
        assert Decimal(filtered.json()["data"]["totals"]["cost_usd"]) == Decimal("0.000003")

        requests = client.get(f"{path}/requests", params={"provider_id": "anthropic"}, headers=headers)
        assert requests.status_code == 200, requests.text
        assert [request["request_id"] for request in requests.json()["data"]["requests"]] == [str(request_id)]
        assert requests.json()["data"]["requests"][0]["status"] == "ok"
        assert Decimal(requests.json()["data"]["requests"][0]["cost_usd"]) == Decimal("0.000003")

        detail = client.get(f"{path}/requests/{request_id}", params={"provider_id": "anthropic"}, headers=headers)
        assert detail.status_code == 200, detail.text
        assert [attempt["provider_id"] for attempt in detail.json()["data"]["attempts"]] == ["openai", "anthropic"]
        assert [attempt["matches_filter"] for attempt in detail.json()["data"]["attempts"]] == [False, True]
        assert Decimal(detail.json()["data"]["cost_usd"]) == Decimal("0.000005")
        lookup = client.get(f"{path}/requests", params={"request_id": str(request_id), "provider_id": "anthropic"}, headers=headers)
        assert Decimal(lookup.json()["data"]["requests"][0]["cost_usd"]) == Decimal("0.000003")
        excluded = client.get(f"{path}/requests", params={"request_id": str(request_id), "provider_id": "other"}, headers=headers)
        assert excluded.json()["data"]["requests"] == []

        attribution = client.get(f"{path}/attribution", params={"group_by": "provider"}, headers=headers)
        assert attribution.status_code == 200, attribution.text
        by_provider = {item["id"]: item for item in attribution.json()["data"]["items"]}
        assert Decimal(by_provider["openai"]["cost_usd"]) == Decimal("0.000002")
        assert Decimal(by_provider["anthropic"]["cost_usd"]) == Decimal("0.000003")


def test_request_export_covers_all_filtered_requests_beyond_first_page(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        org_id = make_org(client, root)
        workspace_id = make_workspace(client, cp.headers(org_id))
        matching = [{**_event(org_id, workspace_id), "provider_id": "anthropic"} for _ in range(3)]
        unrelated = _event(org_id, workspace_id)
        assert client.post("/api/v1/events", json=[*matching, unrelated], headers=root).json()["data"]["ingested"] == 4
        path = f"/api/v1/organizations/{org_id}/reports"
        headers = cp.headers(org_id)

        page = client.get(f"{path}/requests", params={"provider_id": "anthropic", "limit": 1}, headers=headers)
        assert page.status_code == 200, page.text
        assert len(page.json()["data"]["requests"]) == 1
        assert page.json()["data"]["next_offset"] is not None

        export = client.get(f"{path}/requests/export", params={"provider_id": "anthropic"}, headers=headers)
        assert export.status_code == 200, export.text
        rows = list(csv.DictReader(StringIO(export.json()["data"]["csv"])))
        assert {row["request_id"] for row in rows} == {event["request_id"] for event in matching}
        assert sum((Decimal(row["cost_usd"]) for row in rows), Decimal(0)) == Decimal("0.000006")


def test_custom_day_uses_local_midnights_across_dst_transition(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        org_id = make_org(client, root)
        workspace_id = make_workspace(client, cp.headers(org_id))
        times = (
            datetime(2026, 3, 8, 7, 59, 59, tzinfo=UTC),
            datetime(2026, 3, 8, 8, 0, tzinfo=UTC),
            datetime(2026, 3, 9, 6, 59, 59, tzinfo=UTC),
            datetime(2026, 3, 9, 7, 0, tzinfo=UTC),
        )
        events = [_event(org_id, workspace_id, started_at=started_at) for started_at in times]
        assert client.post("/api/v1/events", json=events, headers=root).json()["data"]["ingested"] == 4

        report = client.get(
            f"/api/v1/organizations/{org_id}/reports/usage",
            params={"period": "custom", "timezone": "America/Los_Angeles", "start_date": "2026-03-08", "end_date": "2026-03-08"},
            headers=cp.headers(org_id),
        )
        assert report.status_code == 200, report.text
        data = report.json()["data"]
        assert datetime.fromisoformat(data["period"]["start_at"]) == times[1]
        assert datetime.fromisoformat(data["period"]["end_at"]) == times[3]
        assert data["totals"]["requests"] == 2
        assert Decimal(data["totals"]["cost_usd"]) == Decimal("0.000004")
        assert len(data["daily"]) == 1
        assert data["daily"][0]["requests"] == 2


def test_comparison_uses_the_previous_equal_elapsed_interval(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        org_id = make_org(client, root)
        workspace_id = make_workspace(client, cp.headers(org_id))
        previous_start = datetime(2026, 3, 7, 9, 0, tzinfo=UTC)
        events = [
            _event(org_id, workspace_id, started_at=previous_start - timedelta(seconds=1)),
            _event(org_id, workspace_id, started_at=previous_start),
            _event(org_id, workspace_id, started_at=datetime(2026, 3, 8, 12, 0, tzinfo=UTC)),
        ]
        assert client.post("/api/v1/events", json=events, headers=root).json()["data"]["ingested"] == 3

        report = client.get(
            f"/api/v1/organizations/{org_id}/reports/usage",
            params={"period": "custom", "timezone": "America/Los_Angeles", "start_date": "2026-03-08", "end_date": "2026-03-08"},
            headers=cp.headers(org_id),
        )
        assert report.status_code == 200, report.text
        data = report.json()["data"]
        assert datetime.fromisoformat(data["period"]["previous_start_at"]) == previous_start
        assert datetime.fromisoformat(data["period"]["previous_end_at"]) == datetime(2026, 3, 8, 8, 0, tzinfo=UTC)
        assert data["totals"]["requests"] == 1
        assert data["comparison"]["requests"] == 1
        assert Decimal(data["comparison"]["cost_usd"]) == Decimal("0.000002")


def test_request_id_lookup_finds_authorized_history_outside_selected_period(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        org_id = make_org(client, root)
        workspace_id = make_workspace(client, cp.headers(org_id))
        event = _event(org_id, workspace_id, started_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
        assert client.post("/api/v1/events", json=[event], headers=root).json()["data"]["ingested"] == 1
        path = f"/api/v1/organizations/{org_id}/reports/requests"
        params = {"period": "custom", "start_date": "2026-03-08", "end_date": "2026-03-08"}
        headers = cp.headers(org_id)

        listed = client.get(path, params=params, headers=headers)
        assert listed.status_code == 200, listed.text
        assert listed.json()["data"]["requests"] == []
        lookup = client.get(path, params={**params, "request_id": event["request_id"]}, headers=headers)
        assert lookup.status_code == 200, lookup.text
        assert [request["request_id"] for request in lookup.json()["data"]["requests"]] == [event["request_id"]]
        detail = client.get(f"{path}/{event['request_id']}", params=params, headers=headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["data"]["request_id"] == event["request_id"]
        assert detail.json()["data"]["attempts"][0]["matches_filter"] is True


def test_report_rejects_invalid_period_queries(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers())
        path = f"/api/v1/organizations/{org_id}/reports/usage"
        headers = cp.headers(org_id)
        invalid_queries = (
            {"period": "custom", "start_date": "2026-03-09", "end_date": "2026-03-08"},
            {"period": "custom", "start_date": "2026-03-08"},
            {"period": "30d", "start_date": "2026-03-08", "end_date": "2026-03-08"},
            {"period": "custom", "start_date": "2026-03-08", "end_date": "2026-03-08", "timezone": "No/Such_Zone"},
            {"start_at": "2026-03-08T08:00:00Z"},
            {"start_at": "2026-03-09T08:00:00Z", "end_at": "2026-03-08T08:00:00Z"},
        )
        for params in invalid_queries:
            response = client.get(path, params=params, headers=headers)
            assert response.status_code == 422, (params, response.text)
