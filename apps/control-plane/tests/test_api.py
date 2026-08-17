from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from helpers import MODEL, PROVIDER, make_admin, make_org, make_user, make_workspace, run_in_db, setup_control_plane
from pg import db_name_for, ensure_database

from contract import INFERENCE_TOKEN_PREFIX, SignedBundle, private_key_to_b64, token_hash, uuid7, verify_bundle
from control_plane.app import create_app
from control_plane.authz import Permission
from control_plane.config import BundlePolicy, DatabaseConfig, Settings
from control_plane.models import DataPlaneInstance


def test_management_routes_use_the_api_prefix():
    settings = Settings(
        database=DatabaseConfig(url="postgresql+asyncpg://unused:unused@127.0.0.1/unused"),
        bundle=BundlePolicy(signing_key=private_key_to_b64(Ed25519PrivateKey.generate())),
    )
    paths = set(create_app(settings).openapi()["paths"])
    assert "/api/v1/auth/me" in paths
    assert not any(path.startswith("/v1/") for path in paths)


def _api_user(c, root, tmp_path, email: str = "ops@example.com") -> str:
    user = make_user(tmp_path, email)
    make_admin(tmp_path, user.id)
    return str(user.id)


def test_create_returns_the_full_resource_and_patch_updates_it(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        created = c.post("/api/v1/orgs", json={"name": "o1"}, headers=root).json()["data"]
        assert created["name"] == "o1"
        assert created["created_at"] is not None
        patched = c.patch(f"/api/v1/orgs/{created['id']}", json={"name": "Acme"}, headers=root).json()["data"]
        assert patched["name"] == "Acme"
        assert patched["id"] == created["id"]
        assert c.patch(f"/api/v1/orgs/{uuid7()}", json={"name": "x"}, headers=root).status_code == 404
        assert [o["name"] for o in c.get("/api/v1/orgs", headers=root).json()["data"]] == ["Acme"]


def test_mutation_inputs_reject_unknown_fields(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        response = c.post("/api/v1/orgs", json={"name": "o1", "naem": "typo"}, headers=cp.headers())
        assert response.status_code == 422


def test_full_flow_to_verified_bundle(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        org = cp.headers(o1)
        ws = make_workspace(c, org)
        key = c.post(f"/api/v1/orgs/{o1}/workspaces/{ws}/inference-keys", json={"label": "k"}, headers=org).json()["data"]
        assert key["token"].startswith(INFERENCE_TOKEN_PREFIX)
        assert c.post("/api/v1/instance/taxonomy/providers", json=PROVIDER, headers=root).status_code == 200
        assert c.post("/api/v1/instance/taxonomy/models", json=MODEL, headers=root).status_code == 200
        compiled = c.post(f"/api/v1/orgs/{o1}/bundles/compile", headers=org).json()["data"]
        assert compiled["version"] == 1

        latest = c.get("/api/v1/bundle/latest", params={"org_id": str(o1)}, headers=root)
        assert latest.status_code == 200
        bundle = verify_bundle(SignedBundle.model_validate(latest.json()["data"]), cp.bundle_key.public_key())
        assert str(bundle.bundle_id) == compiled["id"]
        assert [k.key_id for k in bundle.keys] == [key["id"]]
        assert [k.token_hash for k in bundle.keys] == [token_hash(key["token"])]
        assert [k.workspace_id for k in bundle.keys] == [ws]
        (model,) = bundle.catalog.models
        assert model.upstream_model == "gpt-real"
        assert model.input_price_per_mtok == 1.0
        assert model.output_price_per_mtok == 2.0
        assert model.cache_read_price_per_mtok == 0.1
        assert model.cache_write_price_per_mtok == 1.25


def test_revocation_lands_in_next_bundle(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org_id = make_org(c, root, "o1")
        org = cp.headers(org_id)
        ws = make_workspace(c, org)
        key = c.post(f"/api/v1/orgs/{org_id}/workspaces/{ws}/inference-keys", json={"label": "k"}, headers=org).json()["data"]
        c.post(f"/api/v1/orgs/{org_id}/bundles/compile", headers=org)
        assert c.delete(f"/api/v1/orgs/{org_id}/workspaces/{ws}/inference-keys/{key['id']}", headers=org).status_code == 200
        compiled = c.post(f"/api/v1/orgs/{org_id}/bundles/compile", headers=org).json()["data"]
        assert compiled["version"] == 2
        bundle = verify_bundle(
            SignedBundle.model_validate(c.get("/api/v1/bundle/latest", params={"org_id": str(org_id)}, headers=root).json()["data"]),
            cp.bundle_key.public_key(),
        )
        assert bundle.keys == []


def test_updated_at_tracks_modifications(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        c.post("/api/v1/instance/taxonomy/providers", json=PROVIDER, headers=root)
        created = c.get("/api/v1/instance/taxonomy", headers=root).json()["data"]["providers"][0]
        assert created["updated_at"] == created["created_at"]
        c.post("/api/v1/instance/taxonomy/providers", json={**PROVIDER, "base_url": "https://eu.api.openai.com/v1"}, headers=root)
        second = c.get("/api/v1/instance/taxonomy", headers=root).json()["data"]["providers"][0]["updated_at"]
        assert second > created["updated_at"]


def test_serve_refuses_an_unmigrated_database(tmp_path):
    """Fail at startup with the fix named, never one 500 per request against a schemaless database."""
    url = ensure_database(db_name_for(tmp_path))
    settings = Settings(database=DatabaseConfig(url=url), bundle=BundlePolicy(signing_key=private_key_to_b64(Ed25519PrivateKey.generate())))
    with pytest.raises(RuntimeError, match="airllmcp migrate"), TestClient(create_app(settings)):
        pass


def test_healthz_is_unauthenticated_and_touches_the_database(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        res = c.get("/healthz")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}


def test_cross_org_key_revocation_is_not_found(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        o2 = make_org(c, root, "o2")
        ws = make_workspace(c, cp.headers(o1))
        key = c.post(f"/api/v1/orgs/{o1}/workspaces/{ws}/inference-keys", json={"label": "k"}, headers=cp.headers(o1)).json()["data"]
        assert c.delete(f"/api/v1/orgs/{o2}/workspaces/{ws}/inference-keys/{key['id']}", headers=cp.headers(o2)).status_code == 404
        c.post(f"/api/v1/orgs/{o1}/bundles/compile", headers=cp.headers(o1))
        bundle = verify_bundle(
            SignedBundle.model_validate(c.get("/api/v1/bundle/latest", params={"org_id": str(o1)}, headers=root).json()["data"]),
            cp.bundle_key.public_key(),
        )
        assert [k.key_id for k in bundle.keys] == [key["id"]]


def test_the_catalog_refuses_a_credential(tmp_path):
    """Credentials are their own resource now. A taxonomy still carrying credential_ref has to fail
    rather than be ignored, or the operator believes they configured a key the provider does not have."""
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        bad = {**PROVIDER, "credential_ref": "env:OPENAI_API_KEY"}
        assert c.post("/api/v1/instance/taxonomy/providers", json=bad, headers=root).status_code == 422


def test_provider_pricing_multipliers_are_not_part_of_the_catalog(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        bad = {**PROVIDER, "cache_read_multiplier": 0.5}
        assert c.post("/api/v1/instance/taxonomy/providers", json=bad, headers=cp.headers()).status_code == 422


def test_auth_required_everywhere(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        assert c.post("/api/v1/orgs", json={"name": "o1"}).status_code == 401
        assert c.get(f"/api/v1/orgs/{uuid7()}/workspaces").status_code == 401
        assert c.get("/api/v1/instance/taxonomy").status_code == 401
        assert c.post("/api/v1/orgs", json={"name": "o1"}, headers={"authorization": "Bearer garbage"}).status_code == 401
        assert c.get("/api/v1/bundle/latest").status_code == 401
        assert c.get("/api/v1/bundle/latest", headers={"authorization": "Bearer garbage"}).status_code == 401


def test_org_scoped_keys_cannot_use_instance_permissions(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org_id = make_org(c, root, "o1")
        org = cp.headers(org_id)

        assert c.post("/api/v1/orgs", json={"name": "o2"}, headers=org).status_code == 403
        assert c.get("/api/v1/orgs", headers=org).status_code == 403
        assert c.post("/api/v1/instance/taxonomy/providers", json=PROVIDER, headers=org).status_code == 403
        assert c.post("/api/v1/instance/taxonomy/models", json=MODEL, headers=org).status_code == 403
        assert c.get(f"/api/v1/orgs/{org_id}/taxonomy", headers=org).status_code == 200
        assert c.get("/api/v1/instance/taxonomy", headers=root).status_code == 200

        assert c.post(f"/api/v1/orgs/{org_id}/bundles/compile", headers=root).status_code == 200
        for path in (f"/api/v1/orgs/{org_id}/workspaces", f"/api/v1/orgs/{org_id}/bundles", f"/api/v1/orgs/{org_id}/events"):
            assert c.get(path, headers=root).status_code == 200


def test_inference_token_is_rejected_on_management_routes(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org_id = make_org(c, root, "o1")
        org = cp.headers(org_id)
        ws = make_workspace(c, org)
        key = c.post(f"/api/v1/orgs/{org_id}/workspaces/{ws}/inference-keys", json={"label": "k"}, headers=org).json()["data"]
        inference = {"authorization": f"Bearer {key['token']}"}
        assert c.get("/api/v1/orgs", headers=inference).status_code == 401
        assert c.get(f"/api/v1/orgs/{org_id}/workspaces", headers=inference).status_code == 401


def test_orgs_cannot_reach_each_other(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1_id = make_org(c, root, "o1")
        o2_id = make_org(c, root, "o2")
        o1 = cp.headers(o1_id)
        o2 = cp.headers(o2_id)
        c.post("/api/v1/instance/taxonomy/providers", json=PROVIDER, headers=root)
        ws = make_workspace(c, o1)
        key = c.post(f"/api/v1/orgs/{o1_id}/workspaces/{ws}/inference-keys", json={"label": "k"}, headers=o1).json()["data"]

        assert c.delete(f"/api/v1/orgs/{o2_id}/workspaces/{ws}/inference-keys/{key['id']}", headers=o2).status_code == 404
        assert c.get(f"/api/v1/orgs/{o2_id}/workspaces", headers=o2).json()["data"] == []
        taxonomy = c.get(f"/api/v1/orgs/{o2_id}/taxonomy", headers=o2).json()["data"]
        assert [p["name"] for p in taxonomy["providers"]] == ["openai"]
        assert taxonomy == c.get(f"/api/v1/orgs/{o1_id}/taxonomy", headers=o1).json()["data"]


def test_list_endpoints_read_back(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org_id = make_org(c, root, "o1")
        org = cp.headers(org_id)
        ws = make_workspace(c, org)
        key = c.post(f"/api/v1/orgs/{org_id}/workspaces/{ws}/inference-keys", json={"label": "k"}, headers=org).json()["data"]
        c.post("/api/v1/instance/taxonomy/providers", json=PROVIDER, headers=root)
        c.post("/api/v1/instance/taxonomy/models", json=MODEL, headers=root)
        c.post(f"/api/v1/orgs/{org_id}/bundles/compile", headers=org)

        assert [o["name"] for o in c.get("/api/v1/orgs", headers=root).json()["data"]] == ["o1"]
        keys = c.get(f"/api/v1/orgs/{org_id}/workspaces/{ws}/inference-keys", headers=org).json()["data"]
        assert [k["id"] for k in keys] == [key["id"]]
        assert keys[0]["workspace_id"] == str(ws)
        assert "token" not in keys[0]
        assert "token_hash" not in keys[0]
        assert UUID(keys[0]["user_id"]).version == 7
        taxonomy = c.get(f"/api/v1/orgs/{org_id}/taxonomy", headers=org).json()["data"]
        assert [p["name"] for p in taxonomy["providers"]] == ["openai"]
        assert [m["name"] for m in taxonomy["models"]] == ["gpt-test"]
        bundles = c.get(f"/api/v1/orgs/{org_id}/bundles", headers=org).json()["data"]
        assert [b["version"] for b in bundles] == [1]
        assert "payload" not in bundles[0]


def test_bundle_latest_filters_by_org(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        o2 = make_org(c, root, "o2")
        c.post(f"/api/v1/orgs/{o1}/bundles/compile", headers=cp.headers(o1))
        c.post(f"/api/v1/orgs/{o2}/bundles/compile", headers=cp.headers(o2))
        global_latest = verify_bundle(
            SignedBundle.model_validate(c.get("/api/v1/bundle/latest", headers=root).json()["data"]), cp.bundle_key.public_key()
        )
        assert global_latest.org_id == o2
        latest = verify_bundle(
            SignedBundle.model_validate(c.get("/api/v1/bundle/latest", headers=cp.headers(o2)).json()["data"]), cp.bundle_key.public_key()
        )
        assert latest.org_id == o2
        scoped = c.get("/api/v1/bundle/latest", headers=root, params={"org_id": str(o1)})
        bundle = verify_bundle(SignedBundle.model_validate(scoped.json()["data"]), cp.bundle_key.public_key())
        assert bundle.org_id == o1


def test_model_and_provider_upsert_converge(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        c.post("/api/v1/instance/taxonomy/providers", json=PROVIDER, headers=root)
        c.post("/api/v1/instance/taxonomy/models", json={**MODEL, "input_price_per_mtok": 0.0}, headers=root)
        assert c.post("/api/v1/instance/taxonomy/models", json={**MODEL, "input_price_per_mtok": 0.15}, headers=root).status_code == 200
        assert c.get("/api/v1/instance/taxonomy", headers=root).json()["data"]["models"][0]["input_price_per_mtok"] == 0.15
        updated = {**PROVIDER, "base_url": "https://other.example/v1"}
        assert c.post("/api/v1/instance/taxonomy/providers", json=updated, headers=root).status_code == 200
        assert c.get("/api/v1/instance/taxonomy", headers=root).json()["data"]["providers"][0]["base_url"] == "https://other.example/v1"


def test_model_with_unknown_provider_is_not_found(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        assert c.post("/api/v1/instance/taxonomy/models", json={**MODEL, "provider_id": "nope"}, headers=cp.headers()).status_code == 404


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v1/instance/taxonomy/providers", {**PROVIDER, "base_url": "not-a-url"}),
        ("/api/v1/instance/taxonomy/models", {**MODEL, "input_price_per_mtok": -1}),
        ("/api/v1/instance/taxonomy/models", {**MODEL, "context_window": 0}),
        ("/api/v1/instance/taxonomy/models", {**MODEL, "unexpected": True}),
    ],
)
def test_taxonomy_rejects_values_that_cannot_form_a_valid_bundle(tmp_path, path, body):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        if path.endswith("models"):
            assert c.post("/api/v1/instance/taxonomy/providers", json=PROVIDER, headers=root).status_code == 200
        assert c.post(path, json=body, headers=root).status_code == 422


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
        "cost_usd": 0.000004,
        "latency_ms": 120,
        "status": "ok",
        "stream": False,
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
        rows = c.get(f"/api/v1/orgs/{o1}/events", headers=org).json()["data"]
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

        response = c.get(f"/api/v1/orgs/{org_id}/workspaces/{first_workspace}/events", headers=cp.headers(org_id))

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

        stored = c.get(f"/api/v1/orgs/{o1}/events", headers=cp.headers(o1)).json()["data"]
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

        denied = c.post("/api/v1/events", json=[{**event, "provider_id": "", "status": "denied"}], headers=root)
        assert denied.status_code == 200, denied.text


def test_event_pages_walk_newest_to_oldest_without_repeating_rows(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        org_id = make_org(c, root, "o1")
        events = [{**_event(org_id), "event_id": str(UUID(int=index)), "occurred_at": f"2026-08-15T12:00:0{index}+00:00"} for index in range(1, 4)]
        assert c.post("/api/v1/events", json=events, headers=root).status_code == 200
        headers = cp.headers(org_id)

        first = c.get(f"/api/v1/orgs/{org_id}/events", params={"limit": 2}, headers=headers).json()["data"]
        second = c.get(
            f"/api/v1/orgs/{org_id}/events",
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

        newest = c.get(f"/api/v1/orgs/{org_id}/events", params={"limit": 2}, headers=headers).json()["data"]
        older = c.get(
            f"/api/v1/orgs/{org_id}/events",
            params={"before": newest[-1]["occurred_at"], "before_event_id": newest[-1]["event_id"]},
            headers=headers,
        ).json()["data"]
        newer = c.get(
            f"/api/v1/orgs/{org_id}/events",
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
        assert c.get(f"/api/v1/orgs/{org_id}/events", params=params, headers=cp.headers(org_id)).status_code == 422


def _heartbeat(instance_id: UUID) -> dict:
    return {"instance_id": str(instance_id), "version": "0.1.0", "bundle_id": str(uuid7())}


def test_heartbeat_registers_and_lists_instances(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    dp1, dp2, dp3 = uuid7(), uuid7(), uuid7()
    with TestClient(cp.app) as c:
        org_id = make_org(c, root, "o1")
        org = cp.headers(org_id)
        assert c.post("/api/v1/heartbeat", json=_heartbeat(dp1), headers=org).status_code == 200
        assert c.post("/api/v1/heartbeat", json=_heartbeat(dp2), headers=root).status_code == 200
        assert c.post("/api/v1/heartbeat", json=_heartbeat(dp3), headers=root).status_code == 200
        c.post("/api/v1/heartbeat", json=_heartbeat(dp1), headers=org)
        rows = c.get("/api/v1/instance/data-planes", headers=root).json()["data"]
        assert {r["instance_id"] for r in rows} == {str(dp1), str(dp2), str(dp3)}
        assert {row["instance_id"]: row["org_id"] for row in rows} == {str(dp1): str(org_id), str(dp2): None, str(dp3): None}
        assert all(r["status"] == "online" for r in rows)
        assert c.get("/api/v1/instance/data-planes", headers=org).status_code == 403
        assert c.post("/api/v1/heartbeat", json=_heartbeat(uuid7())).status_code == 401


def test_heartbeat_cannot_move_an_instance_between_organizations(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    instance_id = uuid7()
    with TestClient(cp.app) as c:
        first = make_org(c, root, "first")
        second = make_org(c, root, "second")
        assert c.post("/api/v1/heartbeat", json=_heartbeat(instance_id), headers=cp.headers(first)).status_code == 200

        moved = c.post("/api/v1/heartbeat", json=_heartbeat(instance_id), headers=cp.headers(second))

        assert moved.status_code == 409
        instances = c.get("/api/v1/instance/data-planes", headers=root, params={"include_offline": True}).json()["data"]
        assert next(instance for instance in instances if instance["instance_id"] == str(instance_id))["org_id"] == str(first)


def test_heartbeat_cannot_move_a_global_instance_into_an_organization(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    instance_id = uuid7()
    with TestClient(cp.app) as c:
        org_id = make_org(c, root, "dedicated")
        assert c.post("/api/v1/heartbeat", json=_heartbeat(instance_id), headers=root).status_code == 200

        moved = c.post("/api/v1/heartbeat", json=_heartbeat(instance_id), headers=cp.headers(org_id))

        assert moved.status_code == 409
        instances = c.get("/api/v1/instance/data-planes", headers=root, params={"include_offline": True}).json()["data"]
        assert next(instance for instance in instances if instance["instance_id"] == str(instance_id))["org_id"] is None


def test_stale_instance_is_offline_and_hidden_by_default(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org = cp.headers(make_org(c, root, "o1"))
        fresh, gone = uuid7(), uuid7()
        c.post("/api/v1/heartbeat", json=_heartbeat(fresh), headers=org)
        old = datetime.now(tz=UTC) - timedelta(hours=1)
        run_in_db(tmp_path, lambda: DataPlaneInstance(instance_id=gone, version="0.1.0", first_seen=old, last_seen=old).save())
        default = c.get("/api/v1/instance/data-planes", headers=root).json()["data"]
        assert {r["instance_id"] for r in default} == {str(fresh)}
        all_ = c.get("/api/v1/instance/data-planes", headers=root, params={"include_offline": True}).json()["data"]
        by_id = {r["instance_id"]: r["status"] for r in all_}
        assert by_id == {str(fresh): "online", str(gone): "offline"}


def test_revoked_token_is_rejected_on_sync_routes(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        user_id = _api_user(c, root, tmp_path)
        minted = c.post(
            f"/api/v1/orgs/{o1}/access-keys",
            json={
                "user_id": user_id,
                "label": "data-plane",
                "permissions": [Permission.data_planes_heartbeat],
            },
            headers=root,
        ).json()["data"]
        dp = {"authorization": f"Bearer {minted['token']}"}
        dp1 = uuid7()
        assert c.post("/api/v1/heartbeat", json=_heartbeat(dp1), headers=dp).status_code == 200
        assert c.delete(f"/api/v1/access-keys/{minted['id']}", headers=root).status_code == 200
        assert c.post("/api/v1/heartbeat", json=_heartbeat(dp1), headers=dp).status_code == 401
