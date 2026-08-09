from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from helpers import MODEL, PROVIDER, make_admin, make_org, make_workspace, run_in_db, setup_control_plane
from pg import db_name_for, ensure_database

from contract import INFERENCE_TOKEN_PREFIX, SignedBundle, private_key_to_b64, token_hash, uuid7, verify_bundle
from control_plane.app import create_app
from control_plane.config import BundlePolicy, DatabaseConfig, Settings
from control_plane.keys import INSTANCE_KEY_PREFIX, MANAGEMENT_KEY_PREFIX
from control_plane.models import DataPlaneInstance


def _api_user(c, root, tmp_path, email: str = "ops@example.com") -> str:
    uid = c.post("/v1/users", json={"email": email}, headers=root).json()["data"]["id"]
    make_admin(tmp_path, uid)
    return uid


def test_create_returns_the_full_resource_and_patch_updates_it(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        created = c.post("/v1/orgs", json={"name": "o1"}, headers=root).json()["data"]
        assert created["name"] == "o1"
        assert created["created_at"] is not None
        patched = c.patch(f"/v1/orgs/{created['id']}", json={"name": "Acme"}, headers=root).json()["data"]
        assert patched["name"] == "Acme"
        assert patched["id"] == created["id"]
        assert c.patch(f"/v1/orgs/{uuid7()}", json={"name": "x"}, headers=root).status_code == 404
        assert [o["name"] for o in c.get("/v1/orgs", headers=root).json()["data"]] == ["Acme"]


def test_full_flow_to_verified_bundle(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        user_id = _api_user(c, root, tmp_path)
        minted = c.post("/v1/org/management-keys", json={"user_id": user_id, "label": "t"}, headers=cp.headers(o1)).json()["data"]
        org = {"authorization": f"Bearer {minted['token']}"}
        ws = make_workspace(c, org)
        key = c.post(f"/v1/org/workspaces/{ws}/inference-keys", json={"label": "k"}, headers=org).json()["data"]
        assert key["token"].startswith(INFERENCE_TOKEN_PREFIX)
        assert c.post("/v1/taxonomy/providers", json=PROVIDER, headers=root).status_code == 200
        assert c.post("/v1/taxonomy/models", json=MODEL, headers=root).status_code == 200
        compiled = c.post("/v1/org/bundles/compile", headers=org).json()["data"]
        assert compiled["version"] == 1

        latest = c.get("/v1/bundle/latest", headers=root)
        assert latest.status_code == 200
        bundle = verify_bundle(SignedBundle.model_validate(latest.json()["data"]), cp.bundle_key.public_key())
        assert str(bundle.bundle_id) == compiled["id"]
        assert [k.key_id for k in bundle.keys] == [key["id"]]
        assert [k.token_hash for k in bundle.keys] == [token_hash(key["token"])]
        assert [k.workspace_id for k in bundle.keys] == [ws]
        assert bundle.catalog.models[0].upstream_model == "gpt-real"


def test_revocation_lands_in_next_bundle(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org = cp.headers(make_org(c, root, "o1"))
        ws = make_workspace(c, org)
        key = c.post(f"/v1/org/workspaces/{ws}/inference-keys", json={"label": "k"}, headers=org).json()["data"]
        c.post("/v1/org/bundles/compile", headers=org)
        assert c.delete(f"/v1/org/workspaces/{ws}/inference-keys/{key['id']}", headers=org).status_code == 200
        compiled = c.post("/v1/org/bundles/compile", headers=org).json()["data"]
        assert compiled["version"] == 2
        bundle = verify_bundle(SignedBundle.model_validate(c.get("/v1/bundle/latest", headers=root).json()["data"]), cp.bundle_key.public_key())
        assert bundle.keys == []


def test_updated_at_tracks_modifications(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        c.post("/v1/taxonomy/providers", json=PROVIDER, headers=root)
        created = c.get("/v1/taxonomy", headers=root).json()["data"]["providers"][0]
        assert created["updated_at"] == created["created_at"]
        c.post("/v1/taxonomy/providers", json={**PROVIDER, "base_url": "https://eu.api.openai.com/v1"}, headers=root)
        second = c.get("/v1/taxonomy", headers=root).json()["data"]["providers"][0]["updated_at"]
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
        key = c.post(f"/v1/org/workspaces/{ws}/inference-keys", json={"label": "k"}, headers=cp.headers(o1)).json()["data"]
        assert c.delete(f"/v1/org/workspaces/{ws}/inference-keys/{key['id']}", headers=cp.headers(o2)).status_code == 404
        c.post("/v1/org/bundles/compile", headers=cp.headers(o1))
        bundle = verify_bundle(SignedBundle.model_validate(c.get("/v1/bundle/latest", headers=root).json()["data"]), cp.bundle_key.public_key())
        assert [k.key_id for k in bundle.keys] == [key["id"]]


def test_secret_shaped_credential_ref_rejected(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        bad = {**PROVIDER, "credential_ref": "sk-live-abc123"}
        assert c.post("/v1/taxonomy/providers", json=bad, headers=root).status_code == 422


def test_auth_required_everywhere(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        assert c.post("/v1/orgs", json={"name": "o1"}).status_code == 401
        assert c.get("/v1/org/workspaces").status_code == 401
        assert c.get("/v1/taxonomy").status_code == 401
        assert c.post("/v1/orgs", json={"name": "o1"}, headers={"authorization": "Bearer garbage"}).status_code == 401
        assert c.get("/v1/bundle/latest").status_code == 401
        assert c.get("/v1/bundle/latest", headers={"authorization": "Bearer garbage"}).status_code == 401


def test_scopes_are_strictly_separated(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org = cp.headers(make_org(c, root, "o1"))

        assert c.post("/v1/orgs", json={"name": "o2"}, headers=org).status_code == 403
        assert c.get("/v1/orgs", headers=org).status_code == 403
        assert c.get("/v1/instance/management-keys", headers=org).status_code == 403
        assert c.delete(f"/v1/instance/management-keys/{uuid7()}", headers=org).status_code == 403
        assert c.post("/v1/instance/instance-keys", headers=org).status_code == 403
        assert c.get("/v1/instance/instance-keys", headers=org).status_code == 403
        assert c.delete(f"/v1/instance/instance-keys/{uuid7()}", headers=org).status_code == 403

        assert c.post("/v1/taxonomy/providers", json=PROVIDER, headers=org).status_code == 403
        assert c.post("/v1/taxonomy/models", json=MODEL, headers=org).status_code == 403
        assert c.get("/v1/taxonomy", headers=org).status_code == 200
        assert c.get("/v1/taxonomy", headers=root).status_code == 200

        assert c.post("/v1/org/workspaces", headers=root).status_code == 403
        assert c.post("/v1/org/bundles/compile", headers=root).status_code == 403
        for path in ("/v1/org/workspaces", "/v1/org/bundles", "/v1/org/events"):
            assert c.get(path, headers=root).status_code == 403


def test_inference_token_is_rejected_on_management_routes(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org = cp.headers(make_org(c, root, "o1"))
        ws = make_workspace(c, org)
        key = c.post(f"/v1/org/workspaces/{ws}/inference-keys", json={"label": "k"}, headers=org).json()["data"]
        inference = {"authorization": f"Bearer {key['token']}"}
        assert c.get("/v1/orgs", headers=inference).status_code == 401
        assert c.get("/v1/org/workspaces", headers=inference).status_code == 401


def test_orgs_cannot_reach_each_other(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = cp.headers(make_org(c, root, "o1"))
        o2 = cp.headers(make_org(c, root, "o2"))
        c.post("/v1/taxonomy/providers", json=PROVIDER, headers=root)
        ws = make_workspace(c, o1)
        key = c.post(f"/v1/org/workspaces/{ws}/inference-keys", json={"label": "k"}, headers=o1).json()["data"]

        assert c.delete(f"/v1/org/workspaces/{ws}/inference-keys/{key['id']}", headers=o2).status_code == 404
        assert c.get("/v1/org/workspaces", headers=o2).json()["data"] == []
        taxonomy = c.get("/v1/taxonomy", headers=o2).json()["data"]
        assert [p["name"] for p in taxonomy["providers"]] == ["openai"]
        assert taxonomy == c.get("/v1/taxonomy", headers=o1).json()["data"]


def test_token_lifecycle_via_api(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        user_id = _api_user(c, root, tmp_path)
        assert c.post("/v1/org/management-keys", json={"user_id": str(uuid7()), "label": "t"}, headers=cp.headers(o1)).status_code == 404
        assert c.post("/v1/instance/instance-keys", json={"user_id": str(uuid7()), "label": "t"}, headers=root).status_code == 404
        org_token = c.post("/v1/org/management-keys", json={"user_id": user_id, "label": "t"}, headers=cp.headers(o1)).json()["data"]
        assert org_token["org_id"] == str(o1)
        assert org_token["user_id"] == user_id
        assert org_token["token"].startswith(MANAGEMENT_KEY_PREFIX)
        peer = c.post("/v1/instance/instance-keys", json={"user_id": user_id, "label": "t"}, headers=root).json()["data"]
        assert peer["token"].startswith(INSTANCE_KEY_PREFIX)
        listed = c.get("/v1/instance/management-keys", headers=root).json()["data"]
        assert org_token["id"] in {t["id"] for t in listed}
        assert peer["id"] not in {t["id"] for t in listed}
        assert all("token_hash" not in t for t in listed)

        scoped = {"authorization": f"Bearer {org_token['token']}"}
        assert c.get("/v1/org/workspaces", headers=scoped).status_code == 200
        assert c.delete(f"/v1/instance/management-keys/{org_token['id']}", headers=root).status_code == 200
        assert c.get("/v1/org/workspaces", headers=scoped).status_code == 401

        peer_headers = {"authorization": f"Bearer {peer['token']}"}
        assert c.get("/v1/orgs", headers=peer_headers).status_code == 200
        assert c.delete(f"/v1/instance/instance-keys/{peer['id']}", headers=root).status_code == 200
        assert c.get("/v1/orgs", headers=peer_headers).status_code == 401

        assert c.delete(f"/v1/instance/management-keys/{uuid7()}", headers=root).status_code == 404
        assert c.delete(f"/v1/instance/instance-keys/{uuid7()}", headers=root).status_code == 404


def test_list_endpoints_read_back(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org = cp.headers(make_org(c, root, "o1"))
        ws = make_workspace(c, org)
        key = c.post(f"/v1/org/workspaces/{ws}/inference-keys", json={"label": "k"}, headers=org).json()["data"]
        c.post("/v1/taxonomy/providers", json=PROVIDER, headers=root)
        c.post("/v1/taxonomy/models", json=MODEL, headers=root)
        c.post("/v1/org/bundles/compile", headers=org)

        assert [o["name"] for o in c.get("/v1/orgs", headers=root).json()["data"]] == ["o1"]
        keys = c.get(f"/v1/org/workspaces/{ws}/inference-keys", headers=org).json()["data"]
        assert [k["id"] for k in keys] == [key["id"]]
        assert keys[0]["workspace_id"] == str(ws)
        assert "token" not in keys[0]
        assert "token_hash" not in keys[0]
        assert UUID(keys[0]["user_id"]).version == 7
        taxonomy = c.get("/v1/taxonomy", headers=org).json()["data"]
        assert [p["name"] for p in taxonomy["providers"]] == ["openai"]
        assert [m["name"] for m in taxonomy["models"]] == ["gpt-test"]
        bundles = c.get("/v1/org/bundles", headers=org).json()["data"]
        assert [b["version"] for b in bundles] == [1]
        assert "payload" not in bundles[0]


def test_bundle_latest_filters_by_org(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        o2 = make_org(c, root, "o2")
        c.post("/v1/org/bundles/compile", headers=cp.headers(o1))
        c.post("/v1/org/bundles/compile", headers=cp.headers(o2))
        latest = verify_bundle(SignedBundle.model_validate(c.get("/v1/bundle/latest", headers=root).json()["data"]), cp.bundle_key.public_key())
        assert latest.org_id == o2
        scoped = c.get("/v1/bundle/latest", headers=root, params={"org_id": str(o1)})
        bundle = verify_bundle(SignedBundle.model_validate(scoped.json()["data"]), cp.bundle_key.public_key())
        assert bundle.org_id == o1


def test_model_and_provider_upsert_converge(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        c.post("/v1/taxonomy/providers", json=PROVIDER, headers=root)
        c.post("/v1/taxonomy/models", json={**MODEL, "input_price_per_mtok": 0.0}, headers=root)
        assert c.post("/v1/taxonomy/models", json={**MODEL, "input_price_per_mtok": 0.15}, headers=root).status_code == 200
        assert c.get("/v1/taxonomy", headers=root).json()["data"]["models"][0]["input_price_per_mtok"] == 0.15
        updated = {**PROVIDER, "base_url": "https://other.example/v1"}
        assert c.post("/v1/taxonomy/providers", json=updated, headers=root).status_code == 200
        assert c.get("/v1/taxonomy", headers=root).json()["data"]["providers"][0]["base_url"] == "https://other.example/v1"


def test_model_with_unknown_provider_is_not_found(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        assert c.post("/v1/taxonomy/models", json={**MODEL, "provider_id": "nope"}, headers=cp.headers()).status_code == 404


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
        first = c.post("/v1/events", json=events, headers=root).json()["data"]
        assert first == {"received": 3, "ingested": 3}
        replay = c.post("/v1/events", json=events, headers=root).json()["data"]
        assert replay == {"received": 3, "ingested": 0}
        rows = c.get("/v1/org/events", headers=org).json()["data"]
        assert len(rows) == 2
        assert {r["org_id"] for r in rows} == {str(o1)}
        assert c.post("/v1/events", json=[_event(o1)], headers=org).status_code == 200
        assert c.post("/v1/events", json=[_event(o1)], headers=cp.headers(o2)).status_code == 403
        assert c.post("/v1/events", json=events).status_code == 401


def test_event_ingest_survives_a_repeat_inside_one_batch(tmp_path):
    """At-least-once delivery can repeat an event_id within a single flush; the batch still lands."""
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        duplicated = _event(o1)
        other = _event(o1)
        batch = [duplicated, other, duplicated]
        landed = c.post("/v1/events", json=batch, headers=root)
        assert landed.status_code == 200, landed.text
        assert landed.json()["data"] == {"received": 3, "ingested": 2}

        stored = c.get("/v1/org/events", headers=cp.headers(o1)).json()["data"]
        assert sorted(e["event_id"] for e in stored) == sorted({duplicated["event_id"], other["event_id"]})

        replay = c.post("/v1/events", json=batch, headers=root).json()["data"]
        assert replay == {"received": 3, "ingested": 0}


def test_event_ingest_accepts_an_empty_batch(tmp_path):
    """An idle outbox flush posts nothing; it is a no-op, not a malformed statement."""
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        empty = c.post("/v1/events", json=[], headers=root)
        assert empty.status_code == 200, empty.text
        assert empty.json()["data"] == {"received": 0, "ingested": 0}


def _heartbeat(instance_id: UUID) -> dict:
    return {"instance_id": str(instance_id), "version": "0.1.0", "bundle_id": str(uuid7())}


def test_heartbeat_registers_and_lists_instances(tmp_path):
    """A data plane registers against the instance, so either key type may heartbeat and no org is recorded."""
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    dp1, dp2, dp3 = uuid7(), uuid7(), uuid7()
    with TestClient(cp.app) as c:
        org = cp.headers(make_org(c, root, "o1"))
        assert c.post("/v1/heartbeat", json=_heartbeat(dp1), headers=org).status_code == 200
        assert c.post("/v1/heartbeat", json=_heartbeat(dp2), headers=root).status_code == 200
        assert c.post("/v1/heartbeat", json=_heartbeat(dp3), headers=root).status_code == 200
        # re-heartbeat dp1 (upsert, not duplicate)
        c.post("/v1/heartbeat", json=_heartbeat(dp1), headers=org)
        rows = c.get("/v1/instance/data-planes", headers=root).json()["data"]
        assert {r["instance_id"] for r in rows} == {str(dp1), str(dp2), str(dp3)}
        assert all("org_id" not in r for r in rows)
        assert all(r["status"] == "online" for r in rows)
        assert c.get("/v1/instance/data-planes", headers=org).status_code == 403
        assert c.post("/v1/heartbeat", json=_heartbeat(uuid7())).status_code == 401


def test_stale_instance_is_offline_and_hidden_by_default(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org = cp.headers(make_org(c, root, "o1"))
        fresh, gone = uuid7(), uuid7()
        c.post("/v1/heartbeat", json=_heartbeat(fresh), headers=org)
        # backdate a second instance far past the stale window, directly in the db
        old = datetime.now(tz=UTC) - timedelta(hours=1)
        run_in_db(tmp_path, lambda: DataPlaneInstance(instance_id=gone, version="0.1.0", first_seen=old, last_seen=old).save())
        default = c.get("/v1/instance/data-planes", headers=root).json()["data"]
        assert {r["instance_id"] for r in default} == {str(fresh)}  # offline hidden
        all_ = c.get("/v1/instance/data-planes", headers=root, params={"include_offline": True}).json()["data"]
        by_id = {r["instance_id"]: r["status"] for r in all_}
        assert by_id == {str(fresh): "online", str(gone): "offline"}  # record kept


def test_revoked_token_is_rejected_on_sync_routes(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        user_id = _api_user(c, root, tmp_path)
        minted = c.post("/v1/org/management-keys", json={"user_id": user_id, "label": "t"}, headers=cp.headers(o1)).json()["data"]
        dp = {"authorization": f"Bearer {minted['token']}"}
        dp1 = uuid7()
        assert c.post("/v1/heartbeat", json=_heartbeat(dp1), headers=dp).status_code == 200
        assert c.delete(f"/v1/instance/management-keys/{minted['id']}", headers=root).status_code == 200
        assert c.post("/v1/heartbeat", json=_heartbeat(dp1), headers=dp).status_code == 401
