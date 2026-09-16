from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from helpers import make_org, make_workspace, setup_control_plane

from contract import uuid7


def _event(org: UUID) -> dict:
    return {
        "event_id": str(uuid7()),
        "request_id": str(uuid7()),
        "occurred_at": datetime.now(tz=UTC).isoformat(),
        "org_id": str(org),
        "workspace_id": str(uuid7()),
        "key_id": "k1",
        "model_id": "gpt-test",
        "provider_id": "openai",
        "bundle_id": str(uuid4()),
        "input_tokens": 10,
        "output_tokens": 5,
        "max_output_tokens": 128,
        "cost_usd": "0.000004",
        "cost_input_usd": "0.000004",
        "latency_ms": 120,
        "status": "ok",
        "stream": False,
        "credential_id": str(uuid7()),
        "credential_scope": "workspace",
    }


def test_event_ingest_is_idempotent_and_org_scoped(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        o2 = make_org(c, root, "o2")
        org = cp.headers(o1)
        events = [_event(o1), _event(o1), _event(o2)]
        first = c.post("/api/v1/events", json=events, headers=root).json()["data"]
        assert first == {"received": 3, "ingested": 3}
        replay = c.post("/api/v1/events", json=events, headers=root).json()["data"]
        assert replay == {"received": 3, "ingested": 0}
        rows = c.get(f"/api/v1/organizations/{o1}/events", headers=org).json()["data"]
        assert len(rows) == 2
        assert {r["org_id"] for r in rows} == {str(o1)}
        assert c.post("/api/v1/events", json=[_event(o1)], headers=org).status_code == 200
        assert c.post("/api/v1/events", json=[_event(o1)], headers=cp.headers(o2)).status_code == 403
        assert c.post("/api/v1/events", json=events).status_code == 401


def test_event_list_filters_by_workspace(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org_id = make_org(c, root, "o1")
        first_workspace = make_workspace(c, cp.headers(org_id), "first")
        second_workspace = make_workspace(c, cp.headers(org_id), "second")
        first = {**_event(org_id), "workspace_id": str(first_workspace)}
        second = {**_event(org_id), "workspace_id": str(second_workspace)}
        assert c.post("/api/v1/events", json=[first, second], headers=root).status_code == 200

        response = c.get(f"/api/v1/organizations/{org_id}/workspaces/{first_workspace}/events", headers=cp.headers(org_id))

        assert response.status_code == 200, response.text
        assert [event["event_id"] for event in response.json()["data"]] == [first["event_id"]]


def test_event_ingest_survives_a_repeat_inside_one_batch(tmp_path):
    """At-least-once delivery can repeat an event_id within a single flush; the batch still lands."""
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        duplicated = _event(o1)
        other = _event(o1)
        batch = [duplicated, other, duplicated]
        landed = c.post("/api/v1/events", json=batch, headers=root)
        assert landed.status_code == 200, landed.text
        assert landed.json()["data"] == {"received": 3, "ingested": 2}

        stored = c.get(f"/api/v1/organizations/{o1}/events", headers=cp.headers(o1)).json()["data"]
        assert sorted(e["event_id"] for e in stored) == sorted({duplicated["event_id"], other["event_id"]})

        replay = c.post("/api/v1/events", json=batch, headers=root).json()["data"]
        assert replay == {"received": 3, "ingested": 0}


def test_event_ingest_accepts_an_empty_batch(tmp_path):
    """An idle outbox flush posts nothing; it is a no-op, not a malformed statement."""
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        empty = c.post("/api/v1/events", json=[], headers=root)
        assert empty.status_code == 200, empty.text
        assert empty.json()["data"] == {"received": 0, "ingested": 0}


def test_event_ingest_rejects_unbounded_or_ambiguous_events(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        org_id = make_org(c, root, "o1")
        event = _event(org_id)
        assert c.post("/api/v1/events", json=[{**event, "unexpected": True}], headers=root).status_code == 422
        assert c.post("/api/v1/events", json=[{**event, "occurred_at": "2026-08-15T12:00:00"}], headers=root).status_code == 422
        assert c.post("/api/v1/events", json=[{**event, "input_tokens": -1}], headers=root).status_code == 422
        assert c.post("/api/v1/events", json=[{**event, "input_tokens": 2_147_483_648}], headers=root).status_code == 422
        assert c.post("/api/v1/events", json=[{**event, "key_id": ""}], headers=root).status_code == 422
        assert c.post("/api/v1/events", json=[{**event, "model_id": "m" * 256}], headers=root).status_code == 422
        assert c.post("/api/v1/events", json=[{**event, "provider_id": ""}], headers=root).status_code == 422
        assert c.post("/api/v1/events", json=[{**event, "provider_id": "p" * 64}], headers=root).status_code == 422
        assert c.post("/api/v1/events", json=[event] * 1001, headers=root).status_code == 422

        denied = c.post(
            "/api/v1/events",
            json=[
                {
                    **event,
                    "provider_id": "",
                    "status": "denied",
                    "credential_id": None,
                    "credential_scope": None,
                    "cost_usd": "0",
                    "cost_input_usd": "0",
                }
            ],
            headers=root,
        )
        assert denied.status_code == 200, denied.text


def test_event_pages_walk_newest_to_oldest_without_repeating_rows(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        org_id = make_org(c, root, "o1")
        events = [{**_event(org_id), "event_id": str(UUID(int=index)), "occurred_at": f"2026-08-15T12:00:0{index}+00:00"} for index in range(1, 4)]
        assert c.post("/api/v1/events", json=events, headers=root).status_code == 200
        headers = cp.headers(org_id)

        first = c.get(f"/api/v1/organizations/{org_id}/events", params={"limit": 2}, headers=headers).json()["data"]
        second = c.get(
            f"/api/v1/organizations/{org_id}/events",
            params={"limit": 2, "before": first[-1]["occurred_at"], "before_event_id": first[-1]["event_id"]},
            headers=headers,
        ).json()["data"]

        assert [event["event_id"] for event in [*first, *second]] == [str(UUID(int=index)) for index in (3, 2, 1)]


def test_event_cursors_are_stable_when_timestamps_match_and_support_tailing(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        org_id = make_org(c, root, "o1")
        occurred_at = "2026-08-15T12:00:00+00:00"
        events = [{**_event(org_id), "event_id": str(UUID(int=index)), "occurred_at": occurred_at} for index in range(1, 4)]
        assert c.post("/api/v1/events", json=events, headers=root).status_code == 200
        headers = cp.headers(org_id)

        newest = c.get(f"/api/v1/organizations/{org_id}/events", params={"limit": 2}, headers=headers).json()["data"]
        older = c.get(
            f"/api/v1/organizations/{org_id}/events",
            params={"before": newest[-1]["occurred_at"], "before_event_id": newest[-1]["event_id"]},
            headers=headers,
        ).json()["data"]
        newer = c.get(
            f"/api/v1/organizations/{org_id}/events",
            params={"after": older[-1]["occurred_at"], "after_event_id": older[-1]["event_id"]},
            headers=headers,
        ).json()["data"]

        assert [event["event_id"] for event in newest] == [str(UUID(int=3)), str(UUID(int=2))]
        assert [event["event_id"] for event in older] == [str(UUID(int=1))]
        assert [event["event_id"] for event in newer] == [str(UUID(int=2)), str(UUID(int=3))]


@pytest.mark.parametrize(
    "params",
    [
        {"before": "2026-08-15T12:00:00+00:00"},
        {"before_event_id": str(UUID(int=1))},
        {"after": "2026-08-15T12:00:00+00:00"},
        {"after_event_id": str(UUID(int=1))},
        {
            "before": "2026-08-15T12:00:00+00:00",
            "before_event_id": str(UUID(int=1)),
            "after": "2026-08-15T12:00:00+00:00",
            "after_event_id": str(UUID(int=1)),
        },
    ],
)
def test_event_cursor_parameters_must_form_one_complete_pair(tmp_path, params):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        org_id = make_org(c, cp.headers(), "o1")
        assert c.get(f"/api/v1/organizations/{org_id}/events", params=params, headers=cp.headers(org_id)).status_code == 422
