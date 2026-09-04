from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient
from helpers import make_admin, make_org, make_user, run_in_db, setup_control_plane

from contract import uuid7
from control_plane.authz import Permission
from control_plane.models import DataPlaneInstance

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
        o1 = make_org(c, root, "o1")
        user = make_user(tmp_path, "ops@example.com")
        make_admin(tmp_path, user.id)
        user_id = str(user.id)
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
