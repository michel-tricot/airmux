from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from helpers import make_org, make_workspace, setup_control_plane

from api_models import UsageEventOut
from contract import uuid7


def _event(org: UUID) -> dict:
    request_started_at = datetime.now(tz=UTC)
    return {
        "event_id": str(uuid7()),
        "request_id": str(uuid7()),
        "request_started_at": request_started_at.isoformat(),
        "attempt_started_at": request_started_at.isoformat(),
        "occurred_at": request_started_at.isoformat(),
        "org_id": str(org),
        "workspace_id": str(uuid7()),
        "key_id": "k1",
        "authentication_source": "inference_key",
        "authentication_label": "Production key",
        "user_id": str(uuid7()),
        "principal_label": "Checkout service",
        "principal_type": "service_account",
        "workspace_label": "Production",
        "requested_model_id": "gpt-test",
        "requested_capabilities": [],
        "model_id": "gpt-test",
        "provider_id": "openai",
        "bundle_id": str(uuid4()),
        "input_tokens": 10,
        "output_tokens": 5,
        "token_usage_source": "provider",
        "attempt_index": 1,
        "max_output_tokens": 128,
        "input_price_per_mtok": "1",
        "output_price_per_mtok": "2",
        "cache_read_price_per_mtok": "0.1",
        "cache_write_price_per_mtok": "1.25",
        "cost_source": "catalog_estimate",
        "cost_usd": "0.000004",
        "cost_input_usd": "0.000004",
        "latency_ms": 120,
        "status": "ok",
        "stream": False,
        "credential_id": str(uuid7()),
        "credential_scope": "workspace",
        "credential_name": "default",
    }


def _denial(event: dict) -> dict:
    return {
        **event,
        "provider_id": "",
        "status": "denied",
        "token_usage_source": "not_applicable",
        "credential_id": None,
        "credential_scope": None,
        "credential_name": None,
        "attempt_index": None,
        "attempt_started_at": None,
        "input_price_per_mtok": None,
        "output_price_per_mtok": None,
        "cache_read_price_per_mtok": None,
        "cache_write_price_per_mtok": None,
        "cost_source": "not_applicable",
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": "0",
        "cost_input_usd": "0",
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


def test_event_ingest_rejects_one_event_id_with_conflicting_batch_facts(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "event-id-batch-conflict")
        first = _event(org_id)
        conflicting = {**first, "model_id": "other-model"}

        response = client.post("/api/v1/events", json=[first, conflicting], headers=cp.headers())

        assert response.status_code == 409, response.text
        assert client.get(f"/api/v1/organizations/{org_id}/events", headers=cp.headers(org_id)).json()["data"] == []


def test_event_ingest_rejects_one_event_id_with_conflicting_stored_facts(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "event-id-stored-conflict")
        first = _event(org_id)
        conflicting = {**first, "provider_id": "anthropic"}
        assert client.post("/api/v1/events", json=[first], headers=cp.headers()).status_code == 200

        response = client.post("/api/v1/events", json=[conflicting], headers=cp.headers())

        assert response.status_code == 409, response.text
        stored = client.get(f"/api/v1/organizations/{org_id}/events", headers=cp.headers(org_id)).json()["data"]
        assert [(event["event_id"], event["provider_id"]) for event in stored] == [(first["event_id"], first["provider_id"])]


def test_event_ingest_deduplicates_attempt_identity_even_with_a_new_event_id(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "attempt-identity")
        first = _event(org_id)
        duplicate = {**first, "event_id": str(uuid7())}

        response = client.post("/api/v1/events", json=[first, duplicate], headers=cp.headers())

        assert response.status_code == 200, response.text
        assert response.json()["data"] == {"received": 2, "ingested": 1}


@pytest.mark.parametrize("reverse", [False, True], ids=["original-first", "changed-first"])
def test_event_ingest_rejects_conflicting_attempt_identity_and_preserves_first_fact(tmp_path, reverse):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), f"attempt-conflict-{reverse}")
        original = _event(org_id)
        changed = {
            **original,
            "event_id": str(uuid7()),
            "model_id": "fallback-model",
            "provider_id": "anthropic",
            "status": "upstream_error",
            "cost_usd": "0.000006",
            "cost_input_usd": "0.000006",
        }
        first, conflicting = (changed, original) if reverse else (original, changed)
        assert client.post("/api/v1/events", json=[first], headers=cp.headers()).status_code == 200

        response = client.post("/api/v1/events", json=[conflicting], headers=cp.headers())

        assert response.status_code == 409, response.text
        (stored,) = client.get(f"/api/v1/organizations/{org_id}/events", headers=cp.headers(org_id)).json()["data"]
        assert stored["event_id"] == first["event_id"]
        assert stored["model_id"] == first["model_id"]
        assert stored["provider_id"] == first["provider_id"]
        assert Decimal(stored["cost_usd"]) == Decimal(first["cost_usd"])
        assert stored["status"] == first["status"]
        replay = {**first, "event_id": str(uuid7())}
        assert client.post("/api/v1/events", json=[replay], headers=cp.headers()).json()["data"] == {"received": 1, "ingested": 0}


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
                    "token_usage_source": "not_applicable",
                    "credential_id": None,
                    "credential_scope": None,
                    "credential_name": None,
                    "attempt_index": None,
                    "attempt_started_at": None,
                    "input_price_per_mtok": None,
                    "output_price_per_mtok": None,
                    "cache_read_price_per_mtok": None,
                    "cache_write_price_per_mtok": None,
                    "cost_source": "not_applicable",
                    "cost_usd": "0",
                    "cost_input_usd": "0",
                }
            ],
            headers=root,
        )
        assert denied.status_code == 200, denied.text


@pytest.mark.parametrize("source", ["provider", "estimated", "not_applicable"])
def test_token_usage_source_survives_ingestion_and_client_decoding(tmp_path, source):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "usage-source")
        workspace_id = make_workspace(client, cp.headers(org_id), "workspace")
        event = {**_event(org_id), "workspace_id": str(workspace_id), "token_usage_source": source}
        if source == "not_applicable":
            event.update(
                status="denied",
                provider_id="",
                credential_id=None,
                credential_scope=None,
                credential_name=None,
                attempt_index=None,
                attempt_started_at=None,
                input_price_per_mtok=None,
                output_price_per_mtok=None,
                cache_read_price_per_mtok=None,
                cache_write_price_per_mtok=None,
                cost_source="not_applicable",
                input_tokens=0,
                output_tokens=0,
                cost_usd="0",
                cost_input_usd="0",
            )
        response = client.post("/api/v1/events", json=[event], headers=cp.headers())
        assert response.status_code == 200, response.text
        for path in (f"/api/v1/organizations/{org_id}/events", f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/events"):
            response = client.get(path, headers=cp.headers(org_id))
            assert response.status_code == 200, response.text
            stored = UsageEventOut.model_validate(response.json()["data"][0])
            assert stored.token_usage_source.root == source


def test_event_ingest_deduplicates_denial_identity_even_with_a_new_event_id(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "denial-identity")
        denial = _denial(_event(org_id))
        duplicate = {**denial, "event_id": str(uuid7())}

        response = client.post("/api/v1/events", json=[denial, duplicate], headers=cp.headers())

        assert response.status_code == 200, response.text
        assert response.json()["data"] == {"received": 2, "ingested": 1}


def test_event_ingest_rejects_conflicting_denial_identity_and_preserves_first_fact(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "denial-conflict")
        first = _denial(_event(org_id))
        conflicting = {
            **first,
            "event_id": str(uuid7()),
            "authentication_label": "Other key",
            "requested_model_id": "other-model",
            "model_id": "other-model",
        }
        assert client.post("/api/v1/events", json=[first], headers=cp.headers()).status_code == 200

        response = client.post("/api/v1/events", json=[conflicting], headers=cp.headers())

        assert response.status_code == 409, response.text
        stored = client.get(f"/api/v1/organizations/{org_id}/events", headers=cp.headers(org_id)).json()["data"]
        assert [(event["event_id"], event["authentication_label"], event["model_id"]) for event in stored] == [
            (first["event_id"], first["authentication_label"], first["model_id"])
        ]


def test_event_pages_walk_newest_to_oldest_without_repeating_rows(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        org_id = make_org(c, root, "o1")
        events = [
            {
                **_event(org_id),
                "event_id": str(UUID(int=index)),
                "request_started_at": f"2026-08-15T12:00:0{index}+00:00",
                "attempt_started_at": f"2026-08-15T12:00:0{index}+00:00",
                "occurred_at": f"2026-08-15T12:00:0{index}+00:00",
            }
            for index in range(1, 4)
        ]
        assert c.post("/api/v1/events", json=events, headers=root).status_code == 200
        headers = cp.headers(org_id)

        first = c.get(f"/api/v1/organizations/{org_id}/events", params={"limit": 2}, headers=headers).json()
        second = c.get(
            f"/api/v1/organizations/{org_id}/events",
            params={"limit": 2, "cursor": first["page"]["next_cursor"]},
            headers=headers,
        ).json()

        assert [event["event_id"] for event in [*first["data"], *second["data"]]] == [str(UUID(int=index)) for index in (3, 2, 1)]
        assert second["page"]["next_cursor"] is None


def test_event_cursors_are_stable_when_timestamps_match(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        org_id = make_org(c, root, "o1")
        occurred_at = "2026-08-15T12:00:00+00:00"
        events = [
            {
                **_event(org_id),
                "event_id": str(UUID(int=index)),
                "request_started_at": occurred_at,
                "attempt_started_at": occurred_at,
                "occurred_at": occurred_at,
            }
            for index in range(1, 4)
        ]
        assert c.post("/api/v1/events", json=events, headers=root).status_code == 200
        headers = cp.headers(org_id)

        newest = c.get(f"/api/v1/organizations/{org_id}/events", params={"limit": 2}, headers=headers).json()
        older = c.get(
            f"/api/v1/organizations/{org_id}/events",
            params={"cursor": newest["page"]["next_cursor"]},
            headers=headers,
        ).json()["data"]

        assert [event["event_id"] for event in newest["data"]] == [str(UUID(int=3)), str(UUID(int=2))]
        assert [event["event_id"] for event in older] == [str(UUID(int=1))]
