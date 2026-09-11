from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from helpers import make_org, run_in_db, setup_control_plane, setup_db

from contract import BundleManifest, token_hash, uuid7
from control_plane.app import create_app
from control_plane.authz import DATA_PLANE_PERMISSIONS, InstanceRole, Permission
from control_plane.config import DatabaseConfig, DataPlaneBootstrap, Settings
from control_plane.models import DataPlaneInstance, ManagementKey, User, set_actor

if TYPE_CHECKING:
    from uuid import UUID


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
        service_account = c.post(
            "/api/v1/service-accounts",
            json={"name": "Data Plane", "instance_role": InstanceRole.data_plane},
            headers=root,
        ).json()["data"]
        minted = c.post(
            f"/api/v1/service-accounts/{service_account['id']}/management-keys",
            json={
                "label": "data-plane",
                "permissions": [Permission.data_planes_heartbeat],
            },
            headers=root,
        ).json()["data"]
        dp = {"authorization": f"Bearer {minted['token']}"}
        dp1 = uuid7()
        assert c.post("/api/v1/heartbeat", json=_heartbeat(dp1), headers=dp).status_code == 200
        assert c.delete(f"/api/v1/management-keys/{minted['id']}", headers=root).status_code == 200
        assert c.post("/api/v1/heartbeat", json=_heartbeat(dp1), headers=dp).status_code == 401


def _bootstrap_settings(tmp_path, token: str) -> Settings:
    return Settings(database=DatabaseConfig(url=setup_db(tmp_path)), bootstrap=DataPlaneBootstrap(token=token))


def test_supplied_pool_key_bootstraps_authenticated_bundle_access(tmp_path):
    token = "sk-cp-one-shared-pool-secret-that-is-long-enough"
    settings = _bootstrap_settings(tmp_path, token)

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/bundles/manifest", headers={"authorization": f"Bearer {token}"})

    assert response.status_code == 200, response.text
    assert BundleManifest.model_validate(response.json()["data"]) == BundleManifest(bundles=[])

    async def seeded() -> tuple[list[User], list[ManagementKey]]:
        return await User.find(User.service_account == True), await ManagementKey.find()  # noqa: E712 SQLModel builds SQL from this comparison

    users, keys = run_in_db(tmp_path, seeded)
    assert len(users) == len(keys) == 1
    assert users[0].instance_role == InstanceRole.data_plane
    assert keys[0].user_id == users[0].id
    assert keys[0].token_hash == token_hash(token)
    assert set(keys[0].permissions) == DATA_PLANE_PERMISSIONS


def test_bootstrap_is_idempotent_across_control_plane_restarts(tmp_path):
    settings = _bootstrap_settings(tmp_path, "sk-cp-one-shared-pool-secret-that-is-long-enough")

    with TestClient(create_app(settings)):
        pass
    with TestClient(create_app(settings)):
        pass

    async def counts() -> tuple[int, int]:
        return len(await User.find(User.service_account == True)), len(await ManagementKey.find())  # noqa: E712 SQLModel builds SQL from this comparison

    assert run_in_db(tmp_path, counts) == (1, 1)


def test_bootstrap_rejects_a_different_pool_key_after_initialization(tmp_path):
    settings = _bootstrap_settings(tmp_path, "sk-cp-first-shared-pool-secret-that-is-long-enough")
    with TestClient(create_app(settings)):
        pass

    changed = settings.model_copy(update={"bootstrap": DataPlaneBootstrap(token="sk-cp-second-shared-pool-secret-that-is-long-enough")})
    with pytest.raises(RuntimeError, match="does not match"), TestClient(create_app(changed)):
        pass


def test_bootstrap_never_reactivates_a_revoked_pool_key(tmp_path):
    token = "sk-cp-one-shared-pool-secret-that-is-long-enough"
    settings = _bootstrap_settings(tmp_path, token)
    with TestClient(create_app(settings)):
        pass

    async def revoke() -> None:
        key = await ManagementKey.first(ManagementKey.token_hash == token_hash(token))
        assert key is not None
        await set_actor("root")
        key.revoked_at = datetime.now(tz=UTC)
        await key.save()

    run_in_db(tmp_path, revoke)

    with pytest.raises(RuntimeError, match="revoked"), TestClient(create_app(settings)):
        pass


def test_bootstrap_refuses_to_add_authority_after_a_human_claims_the_instance(tmp_path):
    settings = _bootstrap_settings(tmp_path, "sk-cp-one-shared-pool-secret-that-is-long-enough")

    async def claim() -> None:
        user = User(email="owner@example.com", name="Owner", instance_role=InstanceRole.owner)
        await set_actor(user.id)
        await user.save()

    run_in_db(tmp_path, claim)

    with pytest.raises(RuntimeError, match="already claimed"), TestClient(create_app(settings)):
        pass
