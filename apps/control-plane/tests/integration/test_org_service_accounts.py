from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from helpers import make_org, make_workspace, run_in_db, setup_control_plane

from control_plane.authz import Permission
from control_plane.models import ManagementKey, OrgMembership, User

CSRF = {"X-Requested-With": "fetch"}


PASSWORD = "hunter2-hunter2"


def _client(cp) -> TestClient:
    return TestClient(cp.app, base_url="https://testserver")


def _org_admin(client: TestClient, cp, org_id: UUID) -> str:
    account = client.post(
        "/api/v1/auth/signup",
        json={"email": "admin@example.com", "name": "Org Admin", "password": PASSWORD},
    ).json()["data"]
    response = client.put(
        f"/api/v1/orgs/{org_id}/users/{account['user_id']}",
        json={"role": "admin"},
        headers=cp.headers(org_id),
    )
    assert response.status_code == 200, response.text
    return account["user_id"]


def _create(client: TestClient, org_id: UUID, permissions: list[Permission | str] | None = None):
    return client.post(
        f"/api/v1/orgs/{org_id}/service-accounts",
        json={
            "name": "Deploy Bot",
            "management_key": {
                "label": "deployment-management",
                "permissions": permissions or [Permission.organizations_read, Permission.workspaces_read, Permission.workspaces_create],
            },
        },
        headers=CSRF,
    )


def test_org_admin_creates_an_org_owned_service_account_with_a_management_key(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as client:
        org_id = make_org(client, root, "acme")
        _org_admin(client, cp, org_id)

        response = _create(client, org_id)

        assert response.status_code == 200, response.text
        created = response.json()["data"]
        service_account = created["service_account"]
        membership = created["membership"]
        management_key = created["management_key"]
        assert service_account["service_account"] is True
        assert service_account["instance_role"] is None
        assert service_account["managing_org_id"] == str(org_id)
        assert service_account["orgs"] == [str(org_id)]
        assert membership == {
            "user_id": service_account["id"],
            "org_id": str(org_id),
            "role": "admin",
            "status": "member",
        }
        assert management_key["user_id"] == service_account["id"]
        assert management_key["scope"] == {"level": "org", "org_id": str(org_id), "workspace_id": None}
        assert management_key["permissions"] == [
            Permission.organizations_read,
            Permission.workspaces_create,
            Permission.workspaces_read,
        ]

        key_headers = {"authorization": f"Bearer {management_key['token']}"}
        workspace = client.post(f"/api/v1/orgs/{org_id}/workspaces", json={"name": "Production"}, headers=key_headers)
        assert workspace.status_code == 200, workspace.text

        members = client.get(f"/api/v1/orgs/{org_id}/users", headers=CSRF).json()["data"]
        managed = next(member for member in members if member["user_id"] == service_account["id"])
        assert managed["managed"] is True


def test_org_admin_can_issue_a_replacement_key_for_a_managed_service_account(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as client:
        org_id = make_org(client, root, "acme")
        _org_admin(client, cp, org_id)
        created = _create(client, org_id).json()["data"]

        response = client.post(
            f"/api/v1/orgs/{org_id}/service-accounts/{created['service_account']['id']}/management-keys",
            json={
                "label": "replacement-management",
                "permissions": [Permission.workspaces_read],
            },
            headers=CSRF,
        )

        assert response.status_code == 200, response.text
        replacement = response.json()["data"]
        assert replacement["user_id"] == created["service_account"]["id"]
        assert replacement["scope"] == {"level": "org", "org_id": str(org_id), "workspace_id": None}
        assert replacement["permissions"] == [Permission.workspaces_read]
        assert replacement["token"] != created["management_key"]["token"]


def test_workspace_admin_can_issue_a_workspace_key_for_a_managed_service_account(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as client:
        org_id = make_org(client, root, "acme")
        _org_admin(client, cp, org_id)
        workspace_id = make_workspace(client, cp.headers(org_id), "production")
        service_account = _create(client, org_id).json()["data"]["service_account"]

        response = client.post(
            f"/api/v1/orgs/{org_id}/workspaces/{workspace_id}/service-accounts/{service_account['id']}/management-keys",
            json={"label": "workspace-management", "permissions": [Permission.workspaces_read]},
            headers=cp.headers(org_id, workspace_id=workspace_id),
        )

        assert response.status_code == 200, response.text
        key = response.json()["data"]
        assert key["user_id"] == service_account["id"]
        assert key["scope"] == {"level": "workspace", "org_id": str(org_id), "workspace_id": str(workspace_id)}
        assert client.get(f"/api/v1/orgs/{org_id}/workspaces/{workspace_id}", headers={"authorization": f"Bearer {key['token']}"}).status_code == 200


def test_workspace_service_account_key_endpoint_rejects_humans_and_the_wrong_owner(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as client:
        first = make_org(client, root, "first")
        second = make_org(client, root, "second")
        first_workspace = make_workspace(client, cp.headers(first), "first")
        admin_id = _org_admin(client, cp, first)
        service_account = client.post(
            f"/api/v1/orgs/{second}/service-accounts",
            json={
                "name": "Wrong Org Bot",
                "management_key": {"label": "initial", "permissions": [Permission.workspaces_read]},
            },
            headers=root,
        ).json()["data"]["service_account"]
        path = f"/api/v1/orgs/{first}/workspaces/{first_workspace}/service-accounts"
        body = {"label": "wrong-target", "permissions": [Permission.workspaces_read]}

        assert client.post(f"{path}/{admin_id}/management-keys", json=body, headers=root).status_code == 404
        assert client.post(f"{path}/{service_account['id']}/management-keys", json=body, headers=root).status_code == 404


def test_service_account_key_endpoints_reject_humans_and_the_wrong_owner(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as client:
        first = make_org(client, root, "first")
        second = make_org(client, root, "second")
        admin_id = _org_admin(client, cp, first)
        service_account = _create(client, first).json()["data"]["service_account"]
        body = {"label": "wrong-target", "permissions": [Permission.workspaces_read]}

        assert client.post(f"/api/v1/orgs/{first}/service-accounts/{admin_id}/management-keys", json=body, headers=CSRF).status_code == 404
        wrong_org = client.post(
            f"/api/v1/orgs/{second}/service-accounts/{service_account['id']}/management-keys",
            json=body,
            headers=root,
        )
        assert wrong_org.status_code == 404
        assert client.post(f"/api/v1/service-accounts/{service_account['id']}/management-keys", json=body, headers=root).status_code == 404

        instance_service_account = client.post("/api/v1/service-accounts", json={"name": "Global"}, headers=root).json()["data"]
        assert (
            client.put(
                f"/api/v1/orgs/{first}/users/{instance_service_account['id']}",
                json={"role": "admin"},
                headers=root,
            ).status_code
            == 200
        )
        global_path = f"/api/v1/orgs/{first}/service-accounts/{instance_service_account['id']}/management-keys"
        assert client.post(global_path, json=body, headers=CSRF).status_code == 403
        assert client.post(global_path, json=body, headers=root).status_code == 200


def test_service_account_creation_is_atomic_when_the_key_exceeds_its_role(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as client:
        org_id = make_org(client, root, "acme")
        _org_admin(client, cp, org_id)

        response = _create(client, org_id, [Permission.organizations_delete])

        assert response.status_code == 403
        assert "target principal" in response.json()["detail"]
        assert run_in_db(tmp_path, lambda: User.find(User.managing_org_id == org_id)) == []


@pytest.mark.parametrize("permissions", [[Permission.members_manage], [Permission.management_keys_issue]])
def test_service_account_creation_requires_member_management_and_key_issuance(tmp_path, permissions):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as client:
        org_id = make_org(client, root, "acme")
        response = client.post(
            f"/api/v1/orgs/{org_id}/service-accounts",
            json={
                "name": "Deploy Bot",
                "management_key": {"label": "deployment-management", "permissions": [Permission.workspaces_read]},
            },
            headers=cp.headers(org_id, permissions=permissions),
        )
        assert response.status_code == 403
        assert run_in_db(tmp_path, lambda: User.find(User.managing_org_id == org_id)) == []


def test_org_managed_service_account_cannot_be_moved_removed_or_promoted(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as client:
        first = make_org(client, root, "first")
        second = make_org(client, root, "second")
        _org_admin(client, cp, first)
        service_account = _create(client, first).json()["data"]["service_account"]

        moved = client.put(
            f"/api/v1/orgs/{second}/users/{service_account['id']}",
            json={"role": "admin"},
            headers=root,
        )
        promoted = client.put(
            f"/api/v1/orgs/{first}/users/{service_account['id']}",
            json={"role": "owner"},
            headers=root,
        )
        removed = client.delete(f"/api/v1/orgs/{first}/users/{service_account['id']}", headers=root)

        assert moved.status_code == 409
        assert promoted.status_code == 409
        assert removed.status_code == 409
        membership = run_in_db(tmp_path, lambda: OrgMembership.get((UUID(service_account["id"]), first)))
        assert membership is not None
        assert membership.role == "admin"


def test_org_admin_deletes_an_org_managed_service_account_and_its_key(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as client:
        org_id = make_org(client, root, "acme")
        _org_admin(client, cp, org_id)
        created = _create(client, org_id).json()["data"]
        service_account_id = created["service_account"]["id"]
        key_id = created["management_key"]["id"]
        key_headers = {"authorization": f"Bearer {created['management_key']['token']}"}

        response = client.delete(f"/api/v1/orgs/{org_id}/service-accounts/{service_account_id}", headers=CSRF)

        assert response.status_code == 200, response.text
        assert response.json()["data"]["id"] == service_account_id
        assert run_in_db(tmp_path, lambda: User.find_by_id(UUID(service_account_id))) is None
        assert run_in_db(tmp_path, lambda: ManagementKey.find_by_id(UUID(key_id))) is None
        assert client.get(f"/api/v1/orgs/{org_id}/workspaces", headers=key_headers).status_code == 401


def test_deleting_an_org_deletes_its_managed_service_accounts(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as client:
        org_id = make_org(client, root, "acme")
        _org_admin(client, cp, org_id)
        service_account_id = _create(client, org_id).json()["data"]["service_account"]["id"]

        response = client.delete(f"/api/v1/orgs/{org_id}", headers=root)

        assert response.status_code == 200, response.text
        assert run_in_db(tmp_path, lambda: User.find_by_id(UUID(service_account_id))) is None
