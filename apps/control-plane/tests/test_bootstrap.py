from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from helpers import run_in_db, setup_db

from contract import BundleManifest, token_hash
from control_plane.app import create_app
from control_plane.authz import DATA_PLANE_PERMISSIONS, InstanceRole
from control_plane.config import DatabaseConfig, DataPlaneBootstrap, Settings
from control_plane.models import AccessKey, User, set_actor


def _settings(tmp_path, bootstrap: DataPlaneBootstrap) -> Settings:
    return Settings(database=DatabaseConfig(url=setup_db(tmp_path)), bootstrap=bootstrap)


def test_supplied_pool_key_bootstraps_authenticated_bundle_access(tmp_path):
    token = "sk-cp-one-shared-pool-secret-that-is-long-enough"
    settings = _settings(tmp_path, DataPlaneBootstrap(token=token))

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/bundles/manifest", headers={"authorization": f"Bearer {token}"})

    assert response.status_code == 200, response.text
    manifest = BundleManifest.model_validate(response.json()["data"])
    assert manifest == BundleManifest(bundles=[])

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
    settings = _settings(tmp_path, DataPlaneBootstrap(token=token))

    with TestClient(create_app(settings)):
        pass
    with TestClient(create_app(settings)):
        pass

    async def counts() -> tuple[int, int]:
        return len(await User.find(User.service_account == True)), len(await AccessKey.find())  # noqa: E712 SQLModel builds SQL from this comparison

    assert run_in_db(tmp_path, counts) == (1, 1)


def test_bootstrap_rejects_a_different_pool_key_after_initialization(tmp_path):
    settings = _settings(tmp_path, DataPlaneBootstrap(token="sk-cp-first-shared-pool-secret-that-is-long-enough"))
    with TestClient(create_app(settings)):
        pass

    changed = settings.model_copy(update={"bootstrap": DataPlaneBootstrap(token="sk-cp-second-shared-pool-secret-that-is-long-enough")})
    with pytest.raises(RuntimeError, match="does not match"), TestClient(create_app(changed)):
        pass


def test_bootstrap_never_reactivates_a_revoked_pool_key(tmp_path):
    token = "sk-cp-one-shared-pool-secret-that-is-long-enough"
    settings = _settings(tmp_path, DataPlaneBootstrap(token=token))
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
    settings = _settings(tmp_path, DataPlaneBootstrap(token="sk-cp-one-shared-pool-secret-that-is-long-enough"))

    async def claim() -> None:
        user = User(email="owner@example.com", name="Owner", instance_role=InstanceRole.owner)
        await set_actor(user.id)
        await user.save()

    run_in_db(tmp_path, claim)

    with pytest.raises(RuntimeError, match="already claimed"), TestClient(create_app(settings)):
        pass
