from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient
from helpers import make_org, make_workspace, run_in_db, setup_control_plane
from sqlmodel import col

from control_plane.authz import Permission
from control_plane.models import AuditLog, InferenceKey, OrgMembership, PlaygroundSession, WorkspaceMembership


def _signup(client: TestClient, email: str) -> str:
    response = client.post("/api/v1/auth/signup", json={"email": email, "name": email, "password": "hunter2-hunter2"})
    assert response.status_code == 200, response.text
    return response.json()["data"]["user_id"]


def _add_org_member(client: TestClient, cp, org_id: UUID, email: str, role: str = "member") -> str:
    user_id = _signup(client, email)
    response = client.put(f"/api/v1/organizations/{org_id}/users/{user_id}", json={"role": role}, headers=cp.headers(org_id))
    assert response.status_code == 200, response.text
    return user_id


def _add_workspace_member(client: TestClient, cp, org_id: UUID, workspace_id: UUID, user_id: str) -> None:
    response = client.put(
        f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/members/{user_id}",
        json={"role": "member"},
        headers=cp.headers(org_id),
    )
    assert response.status_code == 200, response.text


def _create_key(client: TestClient, workspace_path: str, headers: dict[str, str], user_id: str, label: str) -> dict:
    response = client.post(
        f"{workspace_path}/inference-keys",
        json={"label": label, "user_id": user_id},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_inference_key_owner_is_explicit_and_delegation_is_service_account_only(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app, base_url="https://testserver") as client:
        org_id = make_org(client, root, "acme")
        workspace_id = make_workspace(client, cp.headers(org_id), "production")
        caller_id = _add_org_member(client, cp, org_id, "caller@example.com")
        human_id = _add_org_member(client, cp, org_id, "human@example.com")
        _add_workspace_member(client, cp, org_id, workspace_id, caller_id)
        caller = cp.headers_for(org_id, caller_id, workspace_id)
        base = f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/inference-keys"

        omitted = client.post(base, json={"label": "missing-owner"}, headers=caller)
        assert omitted.status_code == 422
        own = client.post(base, json={"label": "self", "user_id": caller_id}, headers=caller)
        assert own.status_code == 200, own.text

        human = client.post(base, json={"label": "human", "user_id": human_id}, headers=root)
        assert human.status_code == 403
        assert human.json()["detail"] == "Inference keys can only be owned by you or an organization-managed service account"

        service_account = client.post(
            f"/api/v1/organizations/{org_id}/service-accounts",
            json={
                "name": "Production App",
                "management_key": {"label": "initial", "permissions": [Permission.workspaces_read]},
            },
            headers=root,
        ).json()["data"]["service_account"]
        delegated = client.post(base, json={"label": "service", "user_id": service_account["id"]}, headers=root)
        assert delegated.status_code == 200, delegated.text

        caller_owners = client.get(base.replace("/inference-keys", "/inference-key-owners"), headers=caller).json()["data"]
        assert [owner["user_id"] for owner in caller_owners] == [caller_id]
        root_id = client.get("/api/v1/auth/me", headers=root).json()["data"]["user_id"]
        delegated_owners = client.get(base.replace("/inference-keys", "/inference-key-owners"), headers=root).json()["data"]
        assert {owner["user_id"] for owner in delegated_owners} == {root_id, service_account["id"]}

        insufficient = client.post(base, json={"label": "blocked", "user_id": service_account["id"]}, headers=caller)
        assert insufficient.status_code == 403

        other_org = make_org(client, root, "other")
        other_service_account = client.post(
            f"/api/v1/organizations/{other_org}/service-accounts",
            json={
                "name": "Other App",
                "management_key": {"label": "initial", "permissions": [Permission.workspaces_read]},
            },
            headers=root,
        ).json()["data"]["service_account"]
        cross_org = client.post(base, json={"label": "cross-org", "user_id": other_service_account["id"]}, headers=root)
        assert cross_org.status_code == 403
        assert cross_org.json()["detail"] == human.json()["detail"]

        listed = client.get(base, headers=root).json()["data"]
        owners = {key["label"]: key["user_id"] for key in listed}
        assert owners == {"self": caller_id, "service": service_account["id"]}

        delegated_id = delegated.json()["data"]["id"]
        audit = run_in_db(
            tmp_path,
            lambda: AuditLog.first(AuditLog.table_name == "inference_key", AuditLog.record_id == delegated_id, AuditLog.action == "create"),
        )
        assert audit is not None
        assert audit.user_id == root_id
        assert audit.after is not None
        assert audit.after["user_id"] == service_account["id"]


def test_workspace_membership_removal_revokes_only_owned_credentials_in_that_workspace(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app, base_url="https://testserver") as client:
        org_id = make_org(client, root, "acme")
        first = make_workspace(client, cp.headers(org_id), "first")
        second = make_workspace(client, cp.headers(org_id), "second")
        owner_id = _add_org_member(client, cp, org_id, "owner@example.com")
        other_id = _add_org_member(client, cp, org_id, "other@example.com")
        for workspace_id in (first, second):
            _add_workspace_member(client, cp, org_id, workspace_id, owner_id)
        _add_workspace_member(client, cp, org_id, first, other_id)

        owner_first = cp.headers_for(org_id, owner_id, first)
        owner_second = cp.headers_for(org_id, owner_id, second)
        other_first = cp.headers_for(org_id, other_id, first)
        first_path = f"/api/v1/organizations/{org_id}/workspaces/{first}"
        second_path = f"/api/v1/organizations/{org_id}/workspaces/{second}"
        owner_first_key = _create_key(client, first_path, owner_first, owner_id, "owner-first")
        owner_second_key = _create_key(client, second_path, owner_second, owner_id, "owner-second")
        other_first_key = _create_key(client, first_path, other_first, other_id, "other-first")
        owner_first_session = client.put(f"/api/v1/organizations/{org_id}/workspaces/{first}/playground-session", headers=owner_first).json()["data"]
        owner_second_session = client.put(
            f"/api/v1/organizations/{org_id}/workspaces/{second}/playground-session", headers=owner_second
        ).json()["data"]
        other_first_session = client.put(f"/api/v1/organizations/{org_id}/workspaces/{first}/playground-session", headers=other_first).json()["data"]

        removed = client.delete(
            f"/api/v1/organizations/{org_id}/workspaces/{first}/members/{owner_id}",
            headers=cp.headers(org_id),
        )
        assert removed.status_code == 200, removed.text

        def revoked(model, credential_id: str) -> bool:
            credential = run_in_db(tmp_path, lambda: model.find_by_id(UUID(credential_id)))
            assert credential is not None
            return credential.revoked

        assert revoked(InferenceKey, owner_first_key["id"]) is True
        assert revoked(PlaygroundSession, owner_first_session["id"]) is True
        assert revoked(InferenceKey, owner_second_key["id"]) is False
        assert revoked(PlaygroundSession, owner_second_session["id"]) is False
        assert revoked(InferenceKey, other_first_key["id"]) is False
        assert revoked(PlaygroundSession, other_first_session["id"]) is False
        assert client.get(f"/api/v1/organizations/{org_id}/workspaces/{first}/inference-keys", headers=owner_first).status_code == 403

        _add_workspace_member(client, cp, org_id, first, owner_id)
        assert revoked(InferenceKey, owner_first_key["id"]) is True
        assert revoked(PlaygroundSession, owner_first_session["id"]) is True

        root_id = client.get("/api/v1/auth/me", headers=root).json()["data"]["user_id"]
        audit = run_in_db(
            tmp_path,
            lambda: AuditLog.find(
                AuditLog.user_id == root_id,
                col(AuditLog.record_id).in_((owner_first_key["id"], owner_first_session["id"], f"{owner_id}/{first}")),
                AuditLog.action != "create",
            ),
        )
        assert {(entry.table_name, entry.action) for entry in audit} == {
            ("inference_key", "update"),
            ("playground_session", "update"),
            ("workspace_membership", "delete"),
        }


def test_org_membership_removal_revokes_credentials_across_only_that_org_and_last_owner_rolls_back(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app, base_url="https://testserver") as client:
        first_org = make_org(client, root, "first")
        second_org = make_org(client, root, "second")
        first_workspace = make_workspace(client, cp.headers(first_org), "first")
        first_sibling = make_workspace(client, cp.headers(first_org), "sibling")
        second_workspace = make_workspace(client, cp.headers(second_org), "second")
        owner_id = _signup(client, "member@example.com")
        for org_id in (first_org, second_org):
            response = client.put(f"/api/v1/organizations/{org_id}/users/{owner_id}", json={"role": "member"}, headers=cp.headers(org_id))
            assert response.status_code == 200, response.text
        for workspace_id in (first_workspace, first_sibling):
            _add_workspace_member(client, cp, first_org, workspace_id, owner_id)
        _add_workspace_member(client, cp, second_org, second_workspace, owner_id)

        first = cp.headers_for(first_org, owner_id, first_workspace)
        sibling = cp.headers_for(first_org, owner_id, first_sibling)
        second = cp.headers_for(second_org, owner_id, second_workspace)
        first_key = _create_key(client, f"/api/v1/organizations/{first_org}/workspaces/{first_workspace}", first, owner_id, "first")
        sibling_key = _create_key(client, f"/api/v1/organizations/{first_org}/workspaces/{first_sibling}", sibling, owner_id, "sibling")
        second_key = _create_key(client, f"/api/v1/organizations/{second_org}/workspaces/{second_workspace}", second, owner_id, "second")
        first_session = client.put(f"/api/v1/organizations/{first_org}/workspaces/{first_workspace}/playground-session", headers=first).json()["data"]

        removed = client.delete(f"/api/v1/organizations/{first_org}/users/{owner_id}", headers=cp.headers(first_org))
        assert removed.status_code == 200, removed.text
        assert run_in_db(tmp_path, lambda: InferenceKey.find_by_id(UUID(first_key["id"]))).revoked is True
        assert run_in_db(tmp_path, lambda: InferenceKey.find_by_id(UUID(sibling_key["id"]))).revoked is True
        assert run_in_db(tmp_path, lambda: PlaygroundSession.find_by_id(UUID(first_session["id"]))).revoked is True
        assert run_in_db(tmp_path, lambda: InferenceKey.find_by_id(UUID(second_key["id"]))).revoked is False
        first_org_memberships = run_in_db(
            tmp_path,
            lambda: WorkspaceMembership.find(WorkspaceMembership.user_id == UUID(owner_id), WorkspaceMembership.org_id == first_org),
        )
        assert first_org_memberships == []

        last_owner_id = _add_org_member(client, cp, first_org, "last-owner@example.com", "owner")
        last_owner_workspace = cp.headers_for(first_org, last_owner_id, first_workspace)
        _add_workspace_member(client, cp, first_org, first_workspace, last_owner_id)
        last_owner_key = _create_key(
            client,
            f"/api/v1/organizations/{first_org}/workspaces/{first_workspace}",
            last_owner_workspace,
            last_owner_id,
            "last-owner",
        )
        rejected = client.delete(f"/api/v1/organizations/{first_org}/users/{last_owner_id}", headers=cp.headers(first_org))
        assert rejected.status_code == 409
        membership = run_in_db(tmp_path, lambda: OrgMembership.get((UUID(last_owner_id), first_org)))
        key = run_in_db(tmp_path, lambda: InferenceKey.find_by_id(UUID(last_owner_key["id"])))
        assert membership is not None
        assert key is not None
        assert key.revoked is False


def test_principal_deletion_removes_owned_inference_credentials(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app, base_url="https://testserver") as client:
        org_id = make_org(client, root, "acme")
        workspace_id = make_workspace(client, cp.headers(org_id), "production")
        user_id = _add_org_member(client, cp, org_id, "departing@example.com")
        _add_workspace_member(client, cp, org_id, workspace_id, user_id)
        user_headers = cp.headers_for(org_id, user_id, workspace_id)
        key = _create_key(client, f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}", user_headers, user_id, "departing")
        session = client.put(f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/playground-session", headers=user_headers).json()["data"]

        assert client.delete(f"/api/v1/organizations/{org_id}/users/{user_id}", headers=cp.headers(org_id)).status_code == 200
        deleted = client.delete(f"/api/v1/users/{user_id}", headers=root)
        assert deleted.status_code == 200, deleted.text
        assert run_in_db(tmp_path, lambda: InferenceKey.find_by_id(UUID(key["id"]))) is None
        assert run_in_db(tmp_path, lambda: PlaygroundSession.find_by_id(UUID(session["id"]))) is None
