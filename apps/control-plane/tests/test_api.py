from __future__ import annotations

import asyncio

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


def setup_control_plane(tmp_path, monkeypatch) -> Ed25519PrivateKey:
    url = f"sqlite+aiosqlite:///{tmp_path}/cp.db"
    signing_key = Ed25519PrivateKey.generate()
    monkeypatch.setenv("GW_DATABASE_URL", url)
    monkeypatch.setenv("GW_ADMIN_TOKEN", "test-admin")
    monkeypatch.setenv("GW_DP_TOKEN", "test-dp")
    monkeypatch.setenv("GW_SIGNING_KEY", private_key_to_b64(signing_key))
    _create_tables(url)
    return signing_key


def test_full_admin_flow_to_verified_bundle(tmp_path, monkeypatch):
    signing_key = setup_control_plane(tmp_path, monkeypatch)
    with TestClient(app) as c:
        assert c.post("/admin/orgs", json={"id": "o1"}, headers=ADMIN).status_code == 200
        key = c.post("/admin/keys", json={"org_id": "o1"}, headers=ADMIN).json()
        assert verify_api_token(key["token"], signing_key.public_key()).key_id == key["key_id"]
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
    signing_key = setup_control_plane(tmp_path, monkeypatch)
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
