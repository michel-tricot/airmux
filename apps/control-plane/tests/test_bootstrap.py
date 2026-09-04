from __future__ import annotations

import stat
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from helpers import run_in_db, setup_db

from contract import BundleManifest, private_key_to_b64, public_key_to_b64, token_hash
from control_plane.app import create_app
from control_plane.authz import DATA_PLANE_PERMISSIONS, InstanceRole
from control_plane.config import BundlePolicy, DatabaseConfig, FileDataPlaneBootstrap, Settings, TokenDataPlaneBootstrap
from control_plane.models import AccessKey, User, set_actor


def _settings(tmp_path, bootstrap) -> tuple[Settings, Ed25519PrivateKey]:
    signing_key = Ed25519PrivateKey.generate()
    return (
        Settings(
            database=DatabaseConfig(url=setup_db(tmp_path)),
            bundle=BundlePolicy(signing_key=private_key_to_b64(signing_key)),
            bootstrap=bootstrap,
        ),
        signing_key,
    )


def test_file_bootstrap_creates_one_pool_key_and_serves_signing_keys(tmp_path):
    key_path = tmp_path / "state" / "dataplane.key"
    settings, signing_key = _settings(tmp_path, FileDataPlaneBootstrap(path=key_path))

    with TestClient(create_app(settings)) as client:
        token = key_path.read_text(encoding="utf-8")
        response = client.get("/api/v1/bundles/manifest", headers={"authorization": f"Bearer {token}"})

    assert response.status_code == 200, response.text
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    manifest = BundleManifest.model_validate(response.json()["data"])
    assert manifest.signing_keys[0].key_id == "k1"
    assert public_key_to_b64(manifest.signing_keys[0].public_key) == public_key_to_b64(signing_key.public_key())

    async def seeded() -> tuple[list[User], list[AccessKey]]:
        return await User.find(User.service_account == True), await AccessKey.find()  # noqa: E712 SQLModel builds SQL from this comparison

    users, keys = run_in_db(tmp_path, seeded)
    assert len(users) == len(keys) == 1
    assert users[0].instance_role == InstanceRole.data_plane
    assert keys[0].user_id == users[0].id
    assert keys[0].token_hash == token_hash(token)
    assert set(keys[0].permissions) == DATA_PLANE_PERMISSIONS


def test_bootstrap_is_idempotent_across_control_plane_restarts(tmp_path):
    token = "sk-cp-one-shared-pool-secret-that-is-long-enough"
    settings, _ = _settings(tmp_path, TokenDataPlaneBootstrap(token=token))

    with TestClient(create_app(settings)):
        pass
    with TestClient(create_app(settings)):
        pass

    async def counts() -> tuple[int, int]:
        return len(await User.find(User.service_account == True)), len(await AccessKey.find())  # noqa: E712 SQLModel builds SQL from this comparison

    assert run_in_db(tmp_path, counts) == (1, 1)


def test_bootstrap_rejects_a_different_pool_key_after_initialization(tmp_path):
    settings, _ = _settings(tmp_path, TokenDataPlaneBootstrap(token="sk-cp-first-shared-pool-secret-that-is-long-enough"))
    with TestClient(create_app(settings)):
        pass

    changed = settings.model_copy(update={"bootstrap": TokenDataPlaneBootstrap(token="sk-cp-second-shared-pool-secret-that-is-long-enough")})
    with pytest.raises(RuntimeError, match="does not match"), TestClient(create_app(changed)):
        pass


def test_bootstrap_never_reactivates_a_revoked_pool_key(tmp_path):
    token = "sk-cp-one-shared-pool-secret-that-is-long-enough"
    settings, _ = _settings(tmp_path, TokenDataPlaneBootstrap(token=token))
    with TestClient(create_app(settings)):
        pass

    async def revoke() -> None:
        key = await AccessKey.first(AccessKey.token_hash == token_hash(token))
        assert key is not None
        await set_actor("root")
        key.revoked_at = datetime.now(tz=UTC)
        await key.save()

    run_in_db(tmp_path, revoke)

    with pytest.raises(RuntimeError, match="revoked"), TestClient(create_app(settings)):
        pass


def test_bootstrap_refuses_to_add_authority_after_a_human_claims_the_instance(tmp_path):
    settings, _ = _settings(tmp_path, TokenDataPlaneBootstrap(token="sk-cp-one-shared-pool-secret-that-is-long-enough"))

    async def claim() -> None:
        user = User(email="owner@example.com", name="Owner", instance_role=InstanceRole.owner)
        await set_actor(user.id)
        await user.save()

    run_in_db(tmp_path, claim)

    with pytest.raises(RuntimeError, match="already claimed"), TestClient(create_app(settings)):
        pass
