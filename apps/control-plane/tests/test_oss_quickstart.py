from __future__ import annotations

import stat
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from helpers import run_in_db, setup_control_plane

from contract import INFERENCE_TOKEN_PREFIX, uuid7
from control_plane.authz import DATA_PLANE_PERMISSIONS, InstanceRole, OrgRole, Permission, Target
from control_plane.keys import ACCESS_KEY_PREFIX, AccessKeyGrant, mint_access_key
from control_plane.models import DataPlaneInstance, Org, OrgMembership, User, set_actor
from control_plane.routes import oss


@pytest.fixture
def key_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path / oss.DATA_PLANE_KEY_DIR / oss.DATA_PLANE_KEY_FILE


def _data_plane_token(
    tmp_path,
    *,
    instance_role: InstanceRole | None = InstanceRole.data_plane,
    permissions=DATA_PLANE_PERMISSIONS,
    service_account: bool = True,
) -> str:
    async def mint() -> str:
        user = User(
            email=f"data-plane-{uuid7()}@example.com",
            name="Data Plane",
            instance_role=instance_role,
            service_account=service_account,
        )
        await set_actor(user.id)
        await user.save()
        _, token = await mint_access_key(
            AccessKeyGrant(
                principal_id=user.id,
                target=Target.instance(),
                permissions=frozenset(permissions),
                label="data-plane",
            )
        )
        return token

    return run_in_db(tmp_path, mint)


def _org_data_plane_token(tmp_path, *, role: OrgRole = OrgRole.data_plane) -> str:
    async def mint() -> str:
        user = User(email=f"data-plane-{uuid7()}@example.com", name="Data Plane", service_account=True)
        await set_actor(user.id)
        await user.save()
        org = await Org(name=f"Org {uuid7()}").save()
        await OrgMembership(user_id=user.id, org_id=org.id, role=role).save()
        _, token = await mint_access_key(
            AccessKeyGrant(
                principal_id=user.id,
                target=Target.org(org.id),
                permissions=DATA_PLANE_PERMISSIONS,
                label="data-plane",
            )
        )
        return token

    return run_in_db(tmp_path, mint)


def _register_instance(tmp_path) -> None:
    async def insert() -> None:
        now = datetime.now(tz=UTC)
        await DataPlaneInstance(instance_id=uuid7(), version="0.1.0", first_seen=now, last_seen=now).save()

    run_in_db(tmp_path, insert)


def test_oss_quickstart_writes_only_a_live_data_plane_key(tmp_path, key_path):
    cp = setup_control_plane(tmp_path)
    token = _data_plane_token(tmp_path)
    with TestClient(cp.app) as client:
        response = client.post("/v1/instance/oss/quickstart", json={"token": token})
        assert response.status_code == 200, response.text
        assert response.json()["data"]["path"] == str(key_path)
        assert key_path.read_text(encoding="utf-8") == token
        assert stat.S_IMODE(key_path.stat().st_mode) == 0o600


def test_oss_quickstart_is_public(tmp_path, key_path):
    cp = setup_control_plane(tmp_path)
    token = _data_plane_token(tmp_path)
    with TestClient(cp.app) as client:
        assert client.post("/v1/instance/oss/quickstart", json={"token": token}).status_code == 200


def test_oss_quickstart_accepts_an_org_specific_data_plane_key(tmp_path, key_path):
    cp = setup_control_plane(tmp_path)
    token = _org_data_plane_token(tmp_path)
    with TestClient(cp.app) as client:
        assert client.post("/v1/instance/oss/quickstart", json={"token": token}).status_code == 200
        assert key_path.read_text(encoding="utf-8") == token


def test_oss_quickstart_closes_once_a_data_plane_has_registered(tmp_path, key_path):
    cp = setup_control_plane(tmp_path)
    token = _data_plane_token(tmp_path)
    _register_instance(tmp_path)
    with TestClient(cp.app) as client:
        response = client.post("/v1/instance/oss/quickstart", json={"token": token})
        assert response.status_code == 409
        assert not key_path.exists()


@pytest.mark.parametrize("token", ["not-a-key", INFERENCE_TOKEN_PREFIX + "caller-key", ACCESS_KEY_PREFIX + "unknown"])
def test_oss_quickstart_rejects_unknown_credentials(tmp_path, key_path, token):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        response = client.post("/v1/instance/oss/quickstart", json={"token": token})
        assert response.status_code == 422
        assert not key_path.exists()


def test_oss_quickstart_rejects_human_broad_and_wrong_role_keys(tmp_path, key_path):
    cp = setup_control_plane(tmp_path)
    tokens = [
        _data_plane_token(tmp_path, service_account=False, instance_role=InstanceRole.owner),
        _data_plane_token(tmp_path, permissions=DATA_PLANE_PERMISSIONS | {Permission.catalog_read}),
        _data_plane_token(tmp_path, instance_role=None),
        _org_data_plane_token(tmp_path, role=OrgRole.admin),
    ]
    with TestClient(cp.app) as client:
        for token in tokens:
            assert client.post("/v1/instance/oss/quickstart", json={"token": token}).status_code == 422
            assert not key_path.exists()
