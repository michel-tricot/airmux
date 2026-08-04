from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

from contract import SignedBundle, private_key_to_b64, verify_api_token, verify_bundle
from control_plane.app import app

ADMIN = {"authorization": "Bearer test-admin"}
DP = {"authorization": "Bearer test-dp"}

PROVIDER = {
    "org_id": "o1",
    "provider_id": "openai",
    "kind": "openai_compatible",
    "base_url": "https://api.openai.com/v1",
    "credential_ref": "env:OPENAI_API_KEY",
}
MODEL = {"org_id": "o1", "model_id": "gpt-test", "provider_id": "openai", "upstream_model": "gpt-real"}


def _create_tables(url: str) -> None:
    async def create() -> None:
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        await engine.dispose()

    asyncio.run(create())


def setup_control_plane(tmp_path, monkeypatch) -> tuple[Ed25519PrivateKey, Ed25519PrivateKey]:
    url = f"sqlite+aiosqlite:///{tmp_path}/cp.db"
    bundle_key = Ed25519PrivateKey.generate()
    token_key = Ed25519PrivateKey.generate()
    config = (
        "control_plane:\n"
        f"  database:\n    url: {url}\n"
        f'  auth:\n    admin_token: test-admin\n    dp_token: test-dp\n    token_signing_key: "{private_key_to_b64(token_key)}"\n'
        f'  bundle:\n    signing_key: "{private_key_to_b64(bundle_key)}"\n'
    )
    (tmp_path / "airllm.yml").write_text(config, encoding="utf-8")
    monkeypatch.setenv("GW_CONFIG", str(tmp_path / "airllm.yml"))
    _create_tables(url)
    return bundle_key, token_key


def test_full_admin_flow_to_verified_bundle(tmp_path, monkeypatch):
    bundle_key, token_key = setup_control_plane(tmp_path, monkeypatch)
    signing_key = bundle_key
    with TestClient(app) as c:
        assert c.post("/admin/orgs", json={"id": "o1"}, headers=ADMIN).status_code == 200
        key = c.post("/admin/keys", json={"org_id": "o1"}, headers=ADMIN).json()
        claims = verify_api_token(key["token"], token_key.public_key())
        assert claims is not None
        assert claims.key_id == key["key_id"]
        assert verify_api_token(key["token"], bundle_key.public_key()) is None
        assert c.post("/admin/providers", json=PROVIDER, headers=ADMIN).status_code == 200
        assert c.post("/admin/models", json=MODEL, headers=ADMIN).status_code == 200
        compiled = c.post("/admin/bundles/compile", json={"org_id": "o1"}, headers=ADMIN).json()
        assert compiled["version"] == 1

        latest = c.get("/v1/bundle/latest", headers=DP)
        assert latest.status_code == 200
        bundle = verify_bundle(SignedBundle.model_validate(latest.json()), signing_key.public_key())
        assert str(bundle.bundle_id) == compiled["bundle_id"]
        assert [k.key_id for k in bundle.keys] == [key["key_id"]]
        assert bundle.catalog.models[0].upstream_model == "gpt-real"
        assert bundle.revocations == []


def test_revocation_lands_in_next_bundle(tmp_path, monkeypatch):
    signing_key, _ = setup_control_plane(tmp_path, monkeypatch)
    with TestClient(app) as c:
        c.post("/admin/orgs", json={"id": "o1"}, headers=ADMIN)
        key = c.post("/admin/keys", json={"org_id": "o1"}, headers=ADMIN).json()
        c.post("/admin/bundles/compile", json={"org_id": "o1"}, headers=ADMIN)
        assert c.delete(f"/admin/keys/{key['key_id']}", headers=ADMIN).status_code == 200
        compiled = c.post("/admin/bundles/compile", json={"org_id": "o1"}, headers=ADMIN).json()
        assert compiled["version"] == 2
        bundle = verify_bundle(SignedBundle.model_validate(c.get("/v1/bundle/latest", headers=DP).json()), signing_key.public_key())
        assert bundle.keys == []
        assert bundle.revocations == [key["key_id"]]


def test_secret_shaped_credential_ref_rejected(tmp_path, monkeypatch):
    setup_control_plane(tmp_path, monkeypatch)
    with TestClient(app) as c:
        c.post("/admin/orgs", json={"id": "o1"}, headers=ADMIN)
        bad = {**PROVIDER, "credential_ref": "sk-live-abc123"}
        assert c.post("/admin/providers", json=bad, headers=ADMIN).status_code == 422


def test_admin_and_dp_auth_required(tmp_path, monkeypatch):
    setup_control_plane(tmp_path, monkeypatch)
    with TestClient(app) as c:
        assert c.post("/admin/orgs", json={"id": "o1"}).status_code == 401
        assert c.get("/v1/bundle/latest").status_code == 401
        assert c.get("/v1/bundle/latest", headers=ADMIN).status_code == 401


def test_list_endpoints_read_back(tmp_path, monkeypatch):
    setup_control_plane(tmp_path, monkeypatch)
    with TestClient(app) as c:
        c.post("/admin/orgs", json={"id": "o1"}, headers=ADMIN)
        key = c.post("/admin/keys", json={"org_id": "o1"}, headers=ADMIN).json()
        c.post("/admin/providers", json=PROVIDER, headers=ADMIN)
        c.post("/admin/models", json=MODEL, headers=ADMIN)
        c.post("/admin/bundles/compile", json={"org_id": "o1"}, headers=ADMIN)

        assert [o["id"] for o in c.get("/admin/orgs", headers=ADMIN).json()] == ["o1"]
        keys = c.get("/admin/keys", headers=ADMIN, params={"org_id": "o1"}).json()
        assert [k["id"] for k in keys] == [key["key_id"]]
        assert "token" not in keys[0]
        assert [p["id"] for p in c.get("/admin/providers", headers=ADMIN).json()] == ["openai"]
        assert [m["id"] for m in c.get("/admin/models", headers=ADMIN).json()] == ["gpt-test"]
        bundles = c.get("/admin/bundles", headers=ADMIN).json()
        assert [b["version"] for b in bundles] == [1]
        assert "payload" not in bundles[0]
        assert c.get("/admin/orgs").status_code == 401


def test_bundle_latest_filters_by_org(tmp_path, monkeypatch):
    signing_key, _ = setup_control_plane(tmp_path, monkeypatch)
    with TestClient(app) as c:
        c.post("/admin/orgs", json={"id": "o1"}, headers=ADMIN)
        c.post("/admin/orgs", json={"id": "o2"}, headers=ADMIN)
        c.post("/admin/bundles/compile", json={"org_id": "o1"}, headers=ADMIN)
        c.post("/admin/bundles/compile", json={"org_id": "o2"}, headers=ADMIN)
        latest = verify_bundle(SignedBundle.model_validate(c.get("/v1/bundle/latest", headers=DP).json()), signing_key.public_key())
        assert latest.org_id == "o2"
        scoped = c.get("/v1/bundle/latest", headers=DP, params={"org_id": "o1"})
        bundle = verify_bundle(SignedBundle.model_validate(scoped.json()), signing_key.public_key())
        assert bundle.org_id == "o1"


def test_model_and_provider_upsert_converge(tmp_path, monkeypatch):
    setup_control_plane(tmp_path, monkeypatch)
    with TestClient(app) as c:
        c.post("/admin/orgs", json={"id": "o1"}, headers=ADMIN)
        c.post("/admin/providers", json=PROVIDER, headers=ADMIN)
        c.post("/admin/models", json={**MODEL, "input_price_per_mtok": 0.0}, headers=ADMIN)
        assert c.post("/admin/models", json={**MODEL, "input_price_per_mtok": 0.15}, headers=ADMIN).status_code == 200
        models = c.get("/admin/models", headers=ADMIN).json()
        assert models[0]["input_price_per_mtok"] == 0.15
        updated = {**PROVIDER, "base_url": "https://other.example/v1"}
        assert c.post("/admin/providers", json=updated, headers=ADMIN).status_code == 200
        assert c.get("/admin/providers", headers=ADMIN).json()[0]["base_url"] == "https://other.example/v1"


def _event(request_id: str) -> dict:
    return {
        "event_id": str(uuid4()),
        "request_id": request_id,
        "occurred_at": datetime.now(tz=UTC).isoformat(),
        "org_id": "o1",
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


def test_event_ingest_is_idempotent(tmp_path, monkeypatch):
    setup_control_plane(tmp_path, monkeypatch)
    events = [_event("r1"), _event("r2")]
    with TestClient(app) as c:
        first = c.post("/v1/events", json=events, headers=DP).json()
        assert first == {"received": 2, "ingested": 2}
        replay = c.post("/v1/events", json=events, headers=DP).json()
        assert replay == {"received": 2, "ingested": 0}
        rows = c.get("/admin/events", headers=ADMIN).json()
        assert len(rows) == 2
        assert c.post("/v1/events", json=events, headers=ADMIN).status_code == 401
