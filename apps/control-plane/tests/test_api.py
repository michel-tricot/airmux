from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from helpers import MODEL, PROVIDER, run_in_db, setup_control_plane

from contract import SignedBundle, verify_bundle, verify_inference_token
from control_plane.models import DataPlaneInstance
from control_plane.tokens import MANAGEMENT_TOKEN_PREFIX


def test_full_flow_to_verified_bundle(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        assert c.post("/instance/orgs", json={"id": "o1"}, headers=root).status_code == 200
        org = {"authorization": f"Bearer {c.post('/instance/orgs/o1/tokens', headers=root).json()['token']}"}
        key = c.post("/org/keys", json={}, headers=org).json()
        claims = verify_inference_token(key["token"], cp.token_key.public_key())
        assert claims is not None
        assert claims.key_id == key["key_id"]
        assert claims.org_id == "o1"
        assert verify_inference_token(key["token"], cp.bundle_key.public_key()) is None
        assert c.post("/taxonomy/providers", json=PROVIDER, headers=root).status_code == 200
        assert c.post("/taxonomy/models", json=MODEL, headers=root).status_code == 200
        compiled = c.post("/org/bundles/compile", headers=org).json()
        assert compiled["version"] == 1

        latest = c.get("/v1/bundle/latest", headers=root)
        assert latest.status_code == 200
        bundle = verify_bundle(SignedBundle.model_validate(latest.json()), cp.bundle_key.public_key())
        assert str(bundle.bundle_id) == compiled["bundle_id"]
        assert [k.key_id for k in bundle.keys] == [key["key_id"]]
        assert bundle.catalog.models[0].upstream_model == "gpt-real"
        assert bundle.revocations == []


def test_revocation_lands_in_next_bundle(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    org = cp.headers("o1")
    with TestClient(cp.app) as c:
        c.post("/instance/orgs", json={"id": "o1"}, headers=root)
        key = c.post("/org/keys", json={}, headers=org).json()
        c.post("/org/bundles/compile", headers=org)
        assert c.delete(f"/org/keys/{key['key_id']}", headers=org).status_code == 200
        compiled = c.post("/org/bundles/compile", headers=org).json()
        assert compiled["version"] == 2
        bundle = verify_bundle(SignedBundle.model_validate(c.get("/v1/bundle/latest", headers=root).json()), cp.bundle_key.public_key())
        assert bundle.keys == []
        assert bundle.revocations == [key["key_id"]]


def test_updated_at_tracks_modifications(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        c.post("/taxonomy/providers", json=PROVIDER, headers=root)
        created = c.get("/taxonomy", headers=root).json()["providers"][0]
        assert created["updated_at"] == created["created_at"]
        c.post("/taxonomy/providers", json={**PROVIDER, "base_url": "https://eu.api.openai.com/v1"}, headers=root)
        second = c.get("/taxonomy", headers=root).json()["providers"][0]["updated_at"]
        assert second > created["updated_at"]


def test_cross_org_key_revocation_is_not_found(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        c.post("/instance/orgs", json={"id": "o1"}, headers=root)
        c.post("/instance/orgs", json={"id": "o2"}, headers=root)
        key = c.post("/org/keys", json={}, headers=cp.headers("o1")).json()
        assert c.delete(f"/org/keys/{key['key_id']}", headers=cp.headers("o2")).status_code == 404
        c.post("/org/bundles/compile", headers=cp.headers("o1"))
        bundle = verify_bundle(SignedBundle.model_validate(c.get("/v1/bundle/latest", headers=root).json()), cp.bundle_key.public_key())
        assert [k.key_id for k in bundle.keys] == [key["key_id"]]
        assert bundle.revocations == []


def test_secret_shaped_credential_ref_rejected(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        bad = {**PROVIDER, "credential_ref": "sk-live-abc123"}
        assert c.post("/taxonomy/providers", json=bad, headers=root).status_code == 422


def test_auth_required_everywhere(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        assert c.post("/instance/orgs", json={"id": "o1"}).status_code == 401
        assert c.get("/org/keys").status_code == 401
        assert c.get("/taxonomy").status_code == 401
        assert c.post("/instance/orgs", json={"id": "o1"}, headers={"authorization": "Bearer garbage"}).status_code == 401
        assert c.get("/v1/bundle/latest").status_code == 401
        assert c.get("/v1/bundle/latest", headers={"authorization": "Bearer garbage"}).status_code == 401


def test_scopes_are_strictly_separated(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    org = cp.headers("o1")
    with TestClient(cp.app) as c:
        c.post("/instance/orgs", json={"id": "o1"}, headers=root)

        assert c.post("/instance/orgs", json={"id": "o2"}, headers=org).status_code == 403
        assert c.get("/instance/orgs", headers=org).status_code == 403
        assert c.post("/instance/tokens", headers=org).status_code == 403
        assert c.post("/instance/orgs/o1/tokens", headers=org).status_code == 403
        assert c.get("/instance/tokens", headers=org).status_code == 403
        assert c.delete("/instance/tokens/mt-x", headers=org).status_code == 403

        assert c.post("/taxonomy/providers", json=PROVIDER, headers=org).status_code == 403
        assert c.post("/taxonomy/models", json=MODEL, headers=org).status_code == 403
        assert c.get("/taxonomy", headers=org).status_code == 200
        assert c.get("/taxonomy", headers=root).status_code == 200

        assert c.post("/org/keys", json={}, headers=root).status_code == 403
        assert c.post("/org/bundles/compile", headers=root).status_code == 403
        for path in ("/org/keys", "/org/bundles", "/org/events", "/org/instances"):
            assert c.get(path, headers=root).status_code == 403


def test_inference_token_is_rejected_on_management_routes(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    org = cp.headers("o1")
    with TestClient(cp.app) as c:
        c.post("/instance/orgs", json={"id": "o1"}, headers=root)
        key = c.post("/org/keys", json={}, headers=org).json()
        inference = {"authorization": f"Bearer {key['token']}"}
        assert c.get("/instance/orgs", headers=inference).status_code == 401
        assert c.get("/org/keys", headers=inference).status_code == 401


def test_orgs_cannot_reach_each_other(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    o1 = cp.headers("o1")
    o2 = cp.headers("o2")
    with TestClient(cp.app) as c:
        c.post("/instance/orgs", json={"id": "o1"}, headers=root)
        c.post("/instance/orgs", json={"id": "o2"}, headers=root)
        c.post("/taxonomy/providers", json=PROVIDER, headers=root)
        key = c.post("/org/keys", json={}, headers=o1).json()

        assert c.delete(f"/org/keys/{key['key_id']}", headers=o2).status_code == 404
        assert c.get("/org/keys", headers=o2).json() == []
        taxonomy = c.get("/taxonomy", headers=o2).json()
        assert [p["id"] for p in taxonomy["providers"]] == ["openai"]
        assert taxonomy == c.get("/taxonomy", headers=o1).json()


def test_token_lifecycle_via_api(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        c.post("/instance/orgs", json={"id": "o1"}, headers=root)
        assert c.post("/instance/orgs/missing/tokens", headers=root).status_code == 404
        org_token = c.post("/instance/orgs/o1/tokens", headers=root).json()
        assert org_token["org_id"] == "o1"
        assert org_token["token"].startswith(MANAGEMENT_TOKEN_PREFIX)
        peer = c.post("/instance/tokens", headers=root).json()
        assert peer["org_id"] is None
        listed = c.get("/instance/tokens", headers=root).json()
        assert {t["id"] for t in listed} == {org_token["token_id"], peer["token_id"]}

        scoped = {"authorization": f"Bearer {org_token['token']}"}
        assert c.get("/org/keys", headers=scoped).status_code == 200
        assert c.delete(f"/instance/tokens/{org_token['token_id']}", headers=root).status_code == 200
        assert c.get("/org/keys", headers=scoped).status_code == 401

        peer_headers = {"authorization": f"Bearer {peer['token']}"}
        assert c.get("/instance/orgs", headers=peer_headers).status_code == 200
        assert c.delete(f"/instance/tokens/{peer['token_id']}", headers=root).status_code == 200
        assert c.get("/instance/orgs", headers=peer_headers).status_code == 401


def test_offline_minted_token_can_be_tombstoned(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    rogue = cp.headers(token_id="mt-rogue")
    with TestClient(cp.app) as c:
        assert c.get("/instance/orgs", headers=rogue).status_code == 200
        assert c.delete("/instance/tokens/mt-rogue", headers=root).status_code == 200
        assert c.get("/instance/orgs", headers=rogue).status_code == 401


def test_list_endpoints_read_back(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    org = cp.headers("o1")
    with TestClient(cp.app) as c:
        c.post("/instance/orgs", json={"id": "o1"}, headers=root)
        key = c.post("/org/keys", json={}, headers=org).json()
        c.post("/taxonomy/providers", json=PROVIDER, headers=root)
        c.post("/taxonomy/models", json=MODEL, headers=root)
        c.post("/org/bundles/compile", headers=org)

        assert [o["id"] for o in c.get("/instance/orgs", headers=root).json()] == ["o1"]
        keys = c.get("/org/keys", headers=org).json()
        assert [k["id"] for k in keys] == [key["key_id"]]
        assert "token" not in keys[0]
        taxonomy = c.get("/taxonomy", headers=org).json()
        assert [p["id"] for p in taxonomy["providers"]] == ["openai"]
        assert [m["id"] for m in taxonomy["models"]] == ["gpt-test"]
        bundles = c.get("/org/bundles", headers=org).json()
        assert [b["version"] for b in bundles] == [1]
        assert "payload" not in bundles[0]


def test_bundle_latest_filters_by_org(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        c.post("/instance/orgs", json={"id": "o1"}, headers=root)
        c.post("/instance/orgs", json={"id": "o2"}, headers=root)
        c.post("/org/bundles/compile", headers=cp.headers("o1"))
        c.post("/org/bundles/compile", headers=cp.headers("o2"))
        latest = verify_bundle(SignedBundle.model_validate(c.get("/v1/bundle/latest", headers=root).json()), cp.bundle_key.public_key())
        assert latest.org_id == "o2"
        scoped = c.get("/v1/bundle/latest", headers=root, params={"org_id": "o1"})
        bundle = verify_bundle(SignedBundle.model_validate(scoped.json()), cp.bundle_key.public_key())
        assert bundle.org_id == "o1"


def test_model_and_provider_upsert_converge(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        c.post("/taxonomy/providers", json=PROVIDER, headers=root)
        c.post("/taxonomy/models", json={**MODEL, "input_price_per_mtok": 0.0}, headers=root)
        assert c.post("/taxonomy/models", json={**MODEL, "input_price_per_mtok": 0.15}, headers=root).status_code == 200
        assert c.get("/taxonomy", headers=root).json()["models"][0]["input_price_per_mtok"] == 0.15
        updated = {**PROVIDER, "base_url": "https://other.example/v1"}
        assert c.post("/taxonomy/providers", json=updated, headers=root).status_code == 200
        assert c.get("/taxonomy", headers=root).json()["providers"][0]["base_url"] == "https://other.example/v1"


def test_model_with_unknown_provider_is_not_found(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        assert c.post("/taxonomy/models", json={**MODEL, "provider_id": "nope"}, headers=cp.headers()).status_code == 404


def _event(request_id: str, org: str = "o1") -> dict:
    return {
        "event_id": str(uuid4()),
        "request_id": request_id,
        "occurred_at": datetime.now(tz=UTC).isoformat(),
        "org_id": org,
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
    org = cp.headers("o1")
    events = [_event("r1"), _event("r2"), _event("r3", org="o2")]
    with TestClient(cp.app) as c:
        first = c.post("/v1/events", json=events, headers=root).json()
        assert first == {"received": 3, "ingested": 3}
        replay = c.post("/v1/events", json=events, headers=root).json()
        assert replay == {"received": 3, "ingested": 0}
        rows = c.get("/org/events", headers=org).json()
        assert len(rows) == 2
        assert {r["org_id"] for r in rows} == {"o1"}
        assert c.post("/v1/events", json=[_event("r4")], headers=org).status_code == 200
        assert c.post("/v1/events", json=[_event("r5")], headers=cp.headers("o2")).status_code == 403
        assert c.post("/v1/events", json=events).status_code == 401


def _heartbeat(instance_id: str, org: str = "o1") -> dict:
    return {"instance_id": instance_id, "version": "0.1.0", "org_id": org, "bundle_id": str(uuid4())}


def test_heartbeat_registers_and_lists_instances(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    org = cp.headers("o1")
    with TestClient(cp.app) as c:
        assert c.post("/v1/heartbeat", json=_heartbeat("dp-1"), headers=org).status_code == 200
        assert c.post("/v1/heartbeat", json=_heartbeat("dp-2"), headers=root).status_code == 200
        assert c.post("/v1/heartbeat", json=_heartbeat("dp-3", org="o2"), headers=root).status_code == 200
        # re-heartbeat dp-1 (upsert, not duplicate)
        c.post("/v1/heartbeat", json=_heartbeat("dp-1"), headers=org)
        rows = c.get("/org/instances", headers=org).json()
        assert {r["instance_id"] for r in rows} == {"dp-1", "dp-2"}
        assert all(r["status"] == "online" for r in rows)
        assert c.post("/v1/heartbeat", json=_heartbeat("dp-4", org="o2"), headers=org).status_code == 403
        assert c.post("/v1/heartbeat", json=_heartbeat("dp-5")).status_code == 401


def test_stale_instance_is_offline_and_hidden_by_default(tmp_path):
    cp = setup_control_plane(tmp_path)
    org = cp.headers("o1")
    with TestClient(cp.app) as c:
        c.post("/v1/heartbeat", json=_heartbeat("fresh"), headers=org)
        # backdate a second instance far past the stale window, directly in the db
        old = datetime.now(tz=UTC) - timedelta(hours=1)
        run_in_db(tmp_path, lambda: DataPlaneInstance(instance_id="gone", org_id="o1", version="0.1.0", first_seen=old, last_seen=old).save())
        default = c.get("/org/instances", headers=org).json()
        assert {r["instance_id"] for r in default} == {"fresh"}  # offline hidden
        all_ = c.get("/org/instances", headers=org, params={"include_offline": True}).json()
        by_id = {r["instance_id"]: r["status"] for r in all_}
        assert by_id == {"fresh": "online", "gone": "offline"}  # record kept


def test_revoked_token_is_rejected_on_sync_routes(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        c.post("/instance/orgs", json={"id": "o1"}, headers=root)
        minted = c.post("/instance/orgs/o1/tokens", headers=root).json()
        dp = {"authorization": f"Bearer {minted['token']}"}
        assert c.post("/v1/heartbeat", json=_heartbeat("dp-1"), headers=dp).status_code == 200
        assert c.delete(f"/instance/tokens/{minted['token_id']}", headers=root).status_code == 200
        assert c.post("/v1/heartbeat", json=_heartbeat("dp-1"), headers=dp).status_code == 401
