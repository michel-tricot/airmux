"""Deleting a resource: what goes with it, what stays, and what refuses the delete.

A delete takes the rows that exist only to serve the resource. History is not one of those: usage
events keep the ids they were written with and outlive the resource they name. Revocation is the
other verb: a revoked key survives its own revocation.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from helpers import make_org, make_user, make_workspace, run_in_db, setup_control_plane

from contract import uuid7
from control_plane.authz import Permission
from control_plane.models import AccessKey, DataPlaneInstance, InferenceKey, Org, OrgMembership, UsageEvent, Workspace, WorkspaceMembership


def _record_usage(tmp_path, org_id, workspace_id):
    """A usage event for the org, the history a delete must leave behind."""

    async def write():
        await UsageEvent(
            event_id=uuid7(),
            request_id=uuid7(),
            occurred_at=datetime.now(tz=UTC),
            org_id=org_id,
            workspace_id=workspace_id,
            key_id=uuid7(),
            model_id="gpt-test",
            provider_id="openai",
            bundle_id=uuid7(),
            input_tokens=1,
            output_tokens=1,
            cost_usd=0.0,
            latency_ms=1,
            status="ok",
            stream=False,
            credential_id=uuid7(),
            credential_scope="workspace",
        ).save()

    run_in_db(tmp_path, write)


def test_deleting_a_workspace_takes_its_keys_and_members(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org = make_org(c, root, "o1")
        headers = cp.headers(org)
        workspace = make_workspace(c, headers, "staging")
        key = c.post(f"/api/v1/orgs/{org}/workspaces/{workspace}/inference-keys", json={"label": "k"}, headers=headers).json()["data"]

        deleted = c.delete(f"/api/v1/orgs/{org}/workspaces/{workspace}", headers=headers)
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["data"]["id"] == str(workspace)

        assert c.get(f"/api/v1/orgs/{org}/workspaces", headers=headers).json()["data"] == []
        assert run_in_db(tmp_path, lambda: InferenceKey.find_by_id(key["id"])) is None
        assert run_in_db(tmp_path, lambda: WorkspaceMembership.find(WorkspaceMembership.workspace_id == workspace)) == []


def test_deleting_a_workspace_keeps_the_usage_it_recorded(tmp_path):
    """The workspace goes, its events stay and still report under the org that was billed for them."""
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org = make_org(c, root, "o1")
        headers = cp.headers(org)
        workspace = make_workspace(c, headers, "staging")
        _record_usage(tmp_path, org, workspace)

        deleted = c.delete(f"/api/v1/orgs/{org}/workspaces/{workspace}", headers=headers)
        assert deleted.status_code == 200, deleted.text
        assert run_in_db(tmp_path, lambda: Workspace.find_by_id(workspace)) is None

        events = c.get(f"/api/v1/orgs/{org}/events", headers=headers).json()["data"]
        assert [e["workspace_id"] for e in events] == [str(workspace)]


def test_deleting_an_org_takes_its_workspaces_keys_and_memberships(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org = make_org(c, root, "o1")
        headers = cp.headers(org)
        workspace = make_workspace(c, headers, "staging")
        c.post(f"/api/v1/orgs/{org}/workspaces/{workspace}/inference-keys", json={"label": "k"}, headers=headers)
        c.post(
            f"/api/v1/orgs/{org}/access-keys",
            json={"label": "k", "permissions": [Permission.workspaces_read]},
            headers=headers,
        )
        c.post(f"/api/v1/orgs/{org}/bundles/republish", headers=headers)

        deleted = c.delete(f"/api/v1/orgs/{org}", headers=root)
        assert deleted.status_code == 200, deleted.text
        assert c.get("/api/v1/orgs", headers=root).json()["data"] == []
        assert run_in_db(tmp_path, lambda: Workspace.find(Workspace.org_id == org)) == []
        assert run_in_db(tmp_path, lambda: AccessKey.find(AccessKey.org_id == org)) == []
        assert run_in_db(tmp_path, lambda: OrgMembership.find(OrgMembership.org_id == org)) == []


def test_deleting_an_org_keeps_the_usage_it_recorded(tmp_path):
    """No org-scoped credential can reach those events any more, but the rows are still there to bill from."""
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org = make_org(c, root, "o1")
        workspace = make_workspace(c, cp.headers(org), "staging")
        _record_usage(tmp_path, org, workspace)

        deleted = c.delete(f"/api/v1/orgs/{org}", headers=root)
        assert deleted.status_code == 200, deleted.text
        assert run_in_db(tmp_path, lambda: Org.find_by_id(org)) is None
        assert [e.workspace_id for e in run_in_db(tmp_path, lambda: UsageEvent.find(UsageEvent.org_id == org))] == [workspace]


def test_deleting_an_org_keeps_data_plane_history_without_a_dead_foreign_key(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org = make_org(c, root, "o1")
        instance_id = uuid7()

        async def heartbeat():
            now = datetime.now(tz=UTC)
            await DataPlaneInstance(instance_id=instance_id, org_id=org, version="test", first_seen=now, last_seen=now).save()

        run_in_db(tmp_path, heartbeat)
        deleted = c.delete(f"/api/v1/orgs/{org}", headers=root)
        assert deleted.status_code == 200, deleted.text

        instance = run_in_db(tmp_path, lambda: DataPlaneInstance.get(instance_id))
        assert instance is not None
        assert instance.org_id is None


def test_deleting_a_user_takes_their_credentials(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        user = make_user(tmp_path, "gone@example.com")

        deleted = c.delete(f"/api/v1/users/{user.id}", headers=root)
        assert deleted.status_code == 200, deleted.text
        assert c.get(f"/api/v1/users/{user.id}", headers=root).status_code == 404


def test_deleting_a_user_refuses_while_they_hold_a_membership(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org = make_org(c, root, "o1")
        user = make_user(tmp_path, "member@example.com")
        assert c.put(f"/api/v1/orgs/{org}/users/{user.id}", json={"role": "member"}, headers=cp.headers(org)).status_code == 200

        refused = c.delete(f"/api/v1/users/{user.id}", headers=root)
        assert refused.status_code == 409
        assert "member" in refused.json()["detail"]

        assert c.delete(f"/api/v1/orgs/{org}/users/{user.id}", headers=cp.headers(org)).status_code == 200
        assert c.delete(f"/api/v1/users/{user.id}", headers=root).status_code == 200


def test_delete_is_404_for_an_unknown_resource(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org = make_org(c, root, "o1")
        assert c.delete(f"/api/v1/orgs/{uuid7()}", headers=root).status_code == 404
        assert c.delete(f"/api/v1/users/{uuid7()}", headers=root).status_code == 404
        assert c.delete(f"/api/v1/orgs/{org}/workspaces/{uuid7()}", headers=cp.headers(org)).status_code == 404
