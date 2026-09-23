from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from helpers import PROVIDER, make_org, make_user, make_workspace, setup_control_plane

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
        other_org = make_org(client, root, "other-org")
        other_workspace = make_workspace(client, cp.headers(other_org), "other-workspace")
        assert client.get(f"{path}/usage", params={"workspace_id": str(other_workspace)}, headers=org_headers).status_code == 404


def test_provider_filter_counts_matching_cost_and_detail_keeps_all_attempts(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        org_id = make_org(client, root)
        workspace_id = make_workspace(client, cp.headers(org_id))
        request_id = uuid7()
        first = _event(org_id, workspace_id, request_id=request_id)
        first["cache_read_tokens"] = 2
        first["cache_write_tokens"] = 1
        second = {
            **first,
            "event_id": str(uuid7()),
            "provider_id": "anthropic",
            "attempt_started_at": (datetime.fromisoformat(first["attempt_started_at"]) + timedelta(seconds=1)).isoformat(),
            "occurred_at": (datetime.fromisoformat(first["occurred_at"]) + timedelta(seconds=1)).isoformat(),
            "status": "ok",
            "input_tokens": 6,
            "output_tokens": 3,
            "cache_read_tokens": 3,
            "cache_write_tokens": 0,
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
        assert requests.json()["data"]["requests"][0]["cache_read_tokens"] == 3
        assert requests.json()["data"]["requests"][0]["cache_write_tokens"] == 0

        detail = client.get(f"{path}/requests/{request_id}", params={"provider_id": "anthropic"}, headers=headers)
        assert detail.status_code == 200, detail.text
        assert [attempt["provider_id"] for attempt in detail.json()["data"]["attempts"]] == ["openai", "anthropic"]
        assert detail.json()["data"]["within_period"] is True
        assert [attempt["matches_filter"] for attempt in detail.json()["data"]["attempts"]] == [False, True]
        assert Decimal(detail.json()["data"]["cost_usd"]) == Decimal("0.000005")
        assert detail.json()["data"]["cache_read_tokens"] == 5
        assert detail.json()["data"]["cache_write_tokens"] == 1
        lookup = client.get(f"{path}/requests", params={"request_id": str(request_id), "provider_id": "anthropic"}, headers=headers)
        assert Decimal(lookup.json()["data"]["requests"][0]["cost_usd"]) == Decimal("0.000003")
        latest_status = client.get(f"{path}/requests", params={"provider_id": "openai", "status": "ok"}, headers=headers)
        assert [request["request_id"] for request in latest_status.json()["data"]["requests"]] == [str(request_id)]
        excluded = client.get(f"{path}/requests", params={"request_id": str(request_id), "provider_id": "other"}, headers=headers)
        assert excluded.json()["data"]["requests"] == []

        attribution = client.get(f"{path}/attribution", params={"group_by": "provider"}, headers=headers)
        assert attribution.status_code == 200, attribution.text
        by_provider = {item["id"]: item for item in attribution.json()["data"]["items"]}
        assert Decimal(by_provider["openai"]["cost_usd"]) == Decimal("0.000002")
        assert Decimal(by_provider["anthropic"]["cost_usd"]) == Decimal("0.000003")
        options = client.get(f"{path}/filter-options", params={"dimension": "provider", "provider_id": "anthropic"}, headers=headers)
        assert {item["id"] for item in options.json()["data"]["items"]} == {"openai", "anthropic"}


def test_requests_page_by_request_id_and_refresh_without_export(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        org_id = make_org(client, root)
        workspace_id = make_workspace(client, cp.headers(org_id))
        first = _event(org_id, workspace_id)
        second = _event(org_id, workspace_id)
        retry = {
            **second,
            "event_id": str(uuid7()),
            "attempt_started_at": (datetime.fromisoformat(second["attempt_started_at"]) + timedelta(seconds=1)).isoformat(),
            "occurred_at": (datetime.fromisoformat(second["occurred_at"]) + timedelta(seconds=1)).isoformat(),
            "status": "ok",
        }
        third = _event(org_id, workspace_id)
        assert client.post("/api/v1/events", json=[third, retry, first, second], headers=root).json()["data"]["ingested"] == 4

        path = f"/api/v1/organizations/{org_id}/reports/requests"
        headers = cp.headers(org_id)
        expected = [
            event["request_id"]
            for event in sorted((first, second, third), key=lambda event: (event["request_started_at"], event["request_id"]), reverse=True)
        ]
        request_ids = []
        cursor = None
        while True:
            params = {"limit": 1, "cursor": cursor} if cursor is not None else {"limit": 1}
            response = client.get(path, params=params, headers=headers)
            assert response.status_code == 200, response.text
            page = response.json()["data"]
            request_ids.extend(request["request_id"] for request in page["requests"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
        assert request_ids == expected

        filtered = client.get(path, params={"limit": 1, "multiple_attempts": True, "status": "ok"}, headers=headers)
        assert filtered.status_code == 200, filtered.text
        assert [request["request_id"] for request in filtered.json()["data"]["requests"]] == [second["request_id"]]
        assert filtered.json()["data"]["next_cursor"] is None
        assert client.get(f"{path}/export", headers=headers).status_code == 422

        newest = _event(org_id, workspace_id)
        assert client.post("/api/v1/events", json=[newest], headers=root).json()["data"]["ingested"] == 1
        refreshed = client.get(path, params={"limit": 1}, headers=headers)
        assert refreshed.json()["data"]["requests"][0]["request_id"] == newest["request_id"]


def test_request_cursor_orders_non_v7_ids_by_request_time(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        org_id = make_org(client, root)
        workspace_id = make_workspace(client, cp.headers(org_id))
        started_at = datetime.now(UTC) - timedelta(minutes=3)
        older = _event(org_id, workspace_id, request_id=UUID("ffffffff-ffff-4fff-8fff-ffffffffffff"), started_at=started_at)
        newer = _event(
            org_id,
            workspace_id,
            request_id=UUID("00000000-0000-4000-8000-000000000001"),
            started_at=started_at + timedelta(minutes=1),
        )
        tied = _event(
            org_id,
            workspace_id,
            request_id=UUID("00000000-0000-4000-8000-000000000002"),
            started_at=started_at + timedelta(minutes=1),
        )
        assert client.post("/api/v1/events", json=[older, newer, tied], headers=root).json()["data"]["ingested"] == 3

        path = f"/api/v1/organizations/{org_id}/reports/requests"
        headers = cp.headers(org_id)
        first = client.get(path, params={"limit": 1}, headers=headers)
        assert first.status_code == 200, first.text
        assert [request["request_id"] for request in first.json()["data"]["requests"]] == [tied["request_id"]]
        cursor = first.json()["data"]["next_cursor"]
        assert cursor is not None
        second = client.get(path, params={"limit": 1, "cursor": cursor}, headers=headers)
        assert second.status_code == 200, second.text
        assert [request["request_id"] for request in second.json()["data"]["requests"]] == [newer["request_id"]]
        last = client.get(path, params={"limit": 1, "cursor": second.json()["data"]["next_cursor"]}, headers=headers)
        assert last.status_code == 200, last.text
        assert [request["request_id"] for request in last.json()["data"]["requests"]] == [older["request_id"]]
        assert last.json()["data"]["next_cursor"] is None


def test_invalid_event_does_not_block_valid_reporting_or_replay(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        org_id = make_org(client, root)
        workspace_id = make_workspace(client, cp.headers(org_id))
        valid = _event(org_id, workspace_id)
        invalid = {**_event(org_id, workspace_id), "cache_read_tokens": 5}
        batch = [invalid, valid]

        first = client.post("/api/v1/events", json=batch, headers=root)
        assert first.status_code == 200, first.text
        assert first.json()["data"] == {"received": 2, "ingested": 1, "rejected": 1}
        replay = client.post("/api/v1/events", json=batch, headers=root)
        assert replay.status_code == 200, replay.text
        assert replay.json()["data"] == {"received": 2, "ingested": 0, "rejected": 1}

        path = f"/api/v1/organizations/{org_id}/reports"
        headers = cp.headers(org_id)
        totals = client.get(f"{path}/usage", headers=headers).json()["data"]["totals"]
        assert totals["requests"] == 1
        assert totals["input_tokens"] == valid["input_tokens"]
        assert Decimal(totals["cost_usd"]) == Decimal(valid["cost_usd"])
        requests = client.get(f"{path}/requests", headers=headers).json()["data"]["requests"]
        assert [request["request_id"] for request in requests] == [valid["request_id"]]


def test_request_cursor_covers_all_filtered_requests_beyond_first_page(tmp_path):
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

        request_ids = []
        cursor = None
        while True:
            params = {"provider_id": "anthropic", "limit": 1, "cursor": cursor} if cursor is not None else {"provider_id": "anthropic", "limit": 1}
            page = client.get(f"{path}/requests", params=params, headers=headers)
            assert page.status_code == 200, page.text
            data = page.json()["data"]
            request_ids.extend(request["request_id"] for request in data["requests"])
            cursor = data["next_cursor"]
            if cursor is None:
                break
        assert request_ids == [
            event["request_id"] for event in sorted(matching, key=lambda event: (event["request_started_at"], event["request_id"]), reverse=True)
        ]


def test_missing_credential_reconciles_without_an_unusable_filter_option(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        org_id = make_org(client, root)
        workspace_id = make_workspace(client, cp.headers(org_id))
        denied = {
            **_event(org_id, workspace_id),
            "status": "denied",
            "provider_id": "",
            "attempt_started_at": None,
            "token_usage_source": "not_applicable",
            "input_tokens": 0,
            "cost_usd": "0",
            "cost_input_usd": "0",
            "credential_id": None,
            "credential_scope": None,
        }
        assert client.post("/api/v1/events", json=[denied], headers=root).json()["data"]["ingested"] == 1
        path = f"/api/v1/organizations/{org_id}/reports"
        headers = cp.headers(org_id)
        attribution = client.get(f"{path}/attribution", params={"group_by": "credential"}, headers=headers)
        assert attribution.json()["data"]["items"][0]["name"] == "No credential"
        options = client.get(f"{path}/filter-options", params={"dimension": "credential"}, headers=headers)
        assert options.json()["data"]["items"] == []


def test_attribution_does_not_resolve_an_unrelated_users_name(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        org_id = make_org(client, root)
        workspace_id = make_workspace(client, cp.headers(org_id))
        other_workspace_id = make_workspace(client, cp.headers(org_id), "other")
        outsider = make_user(tmp_path, "outside@example.com", "Outside Organization")
        other_member = make_user(tmp_path, "other-workspace@example.com", "Other Workspace")
        assert (
            client.put(f"/api/v1/organizations/{org_id}/users/{other_member.id}", json={"role": "member"}, headers=cp.headers(org_id)).status_code
            == 200
        )
        assert (
            client.put(
                f"/api/v1/organizations/{org_id}/workspaces/{other_workspace_id}/members/{other_member.id}",
                json={"role": "viewer"},
                headers=cp.headers(org_id),
            ).status_code
            == 200
        )
        events = [{**_event(org_id, workspace_id), "user_id": str(user.id)} for user in (outsider, other_member)]
        assert client.post("/api/v1/events", json=events, headers=root).json()["data"]["ingested"] == 2
        report = client.get(f"/api/v1/organizations/{org_id}/reports/attribution", params={"group_by": "owner"}, headers=cp.headers(org_id))
        names = {item["id"]: item["name"] for item in report.json()["data"]["items"]}
        assert names[str(outsider.id)] == str(outsider.id)
        assert names[str(other_member.id)] == "other-workspace@example.com"
        scoped = client.get(
            f"/api/v1/organizations/{org_id}/reports/attribution",
            params={"group_by": "owner", "workspace_id": str(workspace_id)},
            headers=cp.headers(org_id),
        )
        assert {item["name"] for item in scoped.json()["data"]["items"]} == {str(outsider.id), str(other_member.id)}


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
        headers = cp.headers(org_id)
        workspace_id = make_workspace(client, headers, "Reporting workspace")
        user = make_user(tmp_path, "history-owner@example.com")
        assert client.put(f"/api/v1/organizations/{org_id}/users/{user.id}", json={"role": "member"}, headers=headers).status_code == 200
        assert (
            client.put(
                f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/members/{user.id}",
                json={"role": "member"},
                headers=headers,
            ).status_code
            == 200
        )
        user_headers = cp.headers_for(org_id, user.id, workspace_id)
        key = client.post(
            f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/inference-keys",
            json={"label": "Checkout", "user_id": str(user.id)},
            headers=user_headers,
        )
        assert key.status_code == 200, key.text
        assert client.post("/api/v1/instance/taxonomy/providers", json=PROVIDER, headers=root).status_code == 200
        credential = client.post(
            f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/provider-credentials",
            json={"provider": "openai", "name": "Primary", "value": "sk-test"},
            headers=headers,
        )
        assert credential.status_code == 200, credential.text
        event = {
            **_event(org_id, workspace_id, started_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC)),
            "key_id": key.json()["data"]["id"],
            "user_id": str(user.id),
            "credential_id": credential.json()["data"]["id"],
        }
        assert client.post("/api/v1/events", json=[event], headers=root).json()["data"]["ingested"] == 1
        path = f"/api/v1/organizations/{org_id}/reports/requests"
        params = {"period": "custom", "start_date": "2026-03-08", "end_date": "2026-03-08"}

        listed = client.get(path, params=params, headers=headers)
        assert listed.status_code == 200, listed.text
        assert listed.json()["data"]["requests"] == []
        lookup = client.get(path, params={**params, "request_id": event["request_id"]}, headers=headers)
        assert lookup.status_code == 200, lookup.text
        assert [request["request_id"] for request in lookup.json()["data"]["requests"]] == [event["request_id"]]
        assert lookup.json()["data"]["requests"][0]["workspace_name"] == "Reporting workspace"
        assert lookup.json()["data"]["requests"][0]["key_name"] == "Checkout"
        detail = client.get(f"{path}/{event['request_id']}", params=params, headers=headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["data"]["request_id"] == event["request_id"]
        assert detail.json()["data"]["within_period"] is False
        assert detail.json()["data"]["workspace_name"] == "Reporting workspace"
        assert detail.json()["data"]["key_name"] == "Checkout"
        assert detail.json()["data"]["user_email"] == "history-owner@example.com"
        assert detail.json()["data"]["attempts"][0]["credential_name"] == "Primary"
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
            {"period": "custom", "start_date": "2025-01-01", "end_date": "2026-01-02"},
            {"start_at": "2025-01-01T00:00:00Z", "end_at": "2026-01-03T00:00:00Z"},
        )
        for params in invalid_queries:
            response = client.get(path, params=params, headers=headers)
            assert response.status_code == 422, (params, response.text)
