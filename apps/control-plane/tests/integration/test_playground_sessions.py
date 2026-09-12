from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from helpers import make_org, make_user, make_workspace, run_in_db, setup_control_plane
from sqlalchemy import update
from sqlmodel import col

from contract import BundleV1, token_hash, uuid7
from control_plane.authz import Permission
from control_plane.compiler import compile_bundle
from control_plane.db import current_session
from control_plane.models import AuthSession, ManagementKey, PlaygroundSession, set_actor


@pytest.mark.parametrize("loss", ["workspace_removal", "workspace_demotion", "org_removal", "key_revocation", "key_permissions"])
def test_playground_authority_loss_permanently_revokes_and_republishes(tmp_path, loss):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    user = make_user(tmp_path, "playground@example.com")
    with TestClient(cp.app, base_url="https://testserver") as client:
        org_id = make_org(client, root)
        org = cp.headers(org_id)
        workspace_id = make_workspace(client, org)
        member_path = f"/api/v1/orgs/{org_id}/users/{user.id}"
        workspace_member_path = f"/api/v1/orgs/{org_id}/workspaces/{workspace_id}/members/{user.id}"
        assert client.put(member_path, headers=org, json={"role": "member"}).status_code == 200
        assert client.put(workspace_member_path, headers=org, json={"role": "member"}).status_code == 200
        member = cp.headers_for(org_id, user.id, workspace_id)
        path = f"/api/v1/orgs/{org_id}/workspaces/{workspace_id}/playground-session"
        created = client.put(path, headers=member)
        assert created.status_code == 200, created.text
        session_id = UUID(created.json()["data"]["id"])

        if loss == "workspace_removal":
            changed = client.delete(workspace_member_path, headers=org)
        elif loss == "workspace_demotion":
            changed = client.put(workspace_member_path, headers=org, json={"role": "viewer"})
        elif loss == "org_removal":
            changed = client.delete(member_path, headers=org)
        else:

            async def credential_id():
                session = await PlaygroundSession.find_by_id(session_id)
                assert session is not None
                return session.credential_id

            key_id = run_in_db(tmp_path, credential_id)
            key_path = f"/api/v1/management-keys/{key_id}"
            changed = (
                client.delete(key_path, headers=org)
                if loss == "key_revocation"
                else client.put(f"{key_path}/permissions", headers=org, json={"permissions": ["catalog.read"]})
            )
        assert changed.status_code == 200, changed.text
        bundle = BundleV1.model_validate(client.get("/api/v1/bundle/latest", headers=org).json()["data"])
        assert str(session_id) not in {key.key_id for key in bundle.keys}

        async def revoked():
            session = await PlaygroundSession.find_by_id(session_id)
            assert session is not None
            return session.revoked

        assert run_in_db(tmp_path, revoked)
        assert client.put(member_path, headers=org, json={"role": "member"}).status_code == 200
        assert client.put(workspace_member_path, headers=org, json={"role": "member"}).status_code == 200
        bundle = BundleV1.model_validate(client.get("/api/v1/bundle/latest", headers=org).json()["data"])
        assert str(session_id) not in {key.key_id for key in bundle.keys}


def test_playground_expiry_is_capped_by_originating_key(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app, base_url="https://testserver") as client:
        org_id = make_org(client, root)
        org = cp.headers(org_id)
        workspace_id = make_workspace(client, org)
        expiry = datetime.now(tz=UTC) + timedelta(minutes=5)

        async def expire_key():
            key = await ManagementKey.first(ManagementKey.token_hash == token_hash(org["authorization"].removeprefix("Bearer ")))
            assert key is not None
            await set_actor(key.user_id)
            key.expires_at = expiry
            await key.save()

        run_in_db(tmp_path, expire_key)
        response = client.put(f"/api/v1/orgs/{org_id}/workspaces/{workspace_id}/playground-session", headers=org)
        assert response.status_code == 200
        assert datetime.fromisoformat(response.json()["data"]["expires_at"]) == expiry


def test_compiler_rechecks_supporting_authority_independently_of_revocation_hooks(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app, base_url="https://testserver") as client:
        org_id = make_org(client, root)
        org = cp.headers(org_id)
        workspace_id = make_workspace(client, org)
        created = client.put(f"/api/v1/orgs/{org_id}/workspaces/{workspace_id}/playground-session", headers=org)
        assert created.status_code == 200
        session_id = UUID(created.json()["data"]["id"])

        async def compile_after_raw_revocation():
            playground_session = await PlaygroundSession.find_by_id(session_id)
            assert playground_session is not None
            await set_actor(playground_session.user_id)
            now = datetime.now(tz=UTC)
            await current_session().execute(
                update(ManagementKey).where(col(ManagementKey.id) == playground_session.credential_id).values(revoked_at=now)
            )
            assert not playground_session.revoked
            return await compile_bundle(org_id, uuid7(), now)

        assert run_in_db(tmp_path, compile_after_raw_revocation).keys == []


def test_playground_expiry_is_capped_by_browser_session(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app, base_url="https://testserver") as client:
        signup = client.post("/api/v1/auth/signup", json={"email": "browser@example.com", "password": "test-password"})
        assert signup.status_code == 200
        csrf = {"X-Requested-With": "fetch"}
        org_id = make_org(client, csrf)
        workspace_id = make_workspace(client, {**csrf, "X-Test-Org-Id": str(org_id)})
        expiry = datetime.now(tz=UTC) + timedelta(minutes=5)

        async def expire_session():
            auth_session = await AuthSession.first(AuthSession.user_id == UUID(signup.json()["data"]["user_id"]))
            assert auth_session is not None
            auth_session.absolute_expires_at = expiry
            await auth_session.save()

        run_in_db(tmp_path, expire_session)
        response = client.put(f"/api/v1/orgs/{org_id}/workspaces/{workspace_id}/playground-session", headers=csrf)
        assert response.status_code == 200
        assert datetime.fromisoformat(response.json()["data"]["expires_at"]) == expiry


def test_playground_session_is_cookie_only_short_lived_and_reused(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app, base_url="https://testserver") as client:
        org_id = make_org(client, root)
        org = cp.headers(org_id)
        workspace_id = make_workspace(client, org)
        path = f"/api/v1/orgs/{org_id}/workspaces/{workspace_id}/playground-session"

        first = client.put(path, headers=org)
        assert first.status_code == 200, first.text
        session = first.json()["data"]
        assert set(session) == {"id", "expires_at", "status"}
        assert session["status"] == "ready"
        expires_at = datetime.fromisoformat(session["expires_at"])
        assert datetime.now(tz=UTC) + timedelta(minutes=4) < expires_at <= datetime.now(tz=UTC) + timedelta(minutes=5)
        cookie = first.headers["set-cookie"]
        assert "airllm_playground=" in cookie
        assert "HttpOnly" in cookie
        assert "SameSite=strict" in cookie
        assert "Secure" in cookie

        second = client.put(path, headers=org)
        assert second.status_code == 200
        assert second.json()["data"] == session
        assert "set-cookie" not in second.headers

        assert client.get(f"/api/v1/orgs/{org_id}/workspaces/{workspace_id}/inference-keys", headers=org).json()["data"] == []
        bundle = BundleV1.model_validate(client.get("/api/v1/bundle/latest", headers=org).json()["data"])
        assert len(bundle.keys) == 1
        assert bundle.keys[0].key_id == session["id"]
        assert bundle.keys[0].expires_at == expires_at


def test_ending_a_playground_session_clears_the_cookie_and_bundle_entry(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app, base_url="https://testserver") as client:
        org_id = make_org(client, root)
        org = cp.headers(org_id)
        workspace_id = make_workspace(client, org)
        path = f"/api/v1/orgs/{org_id}/workspaces/{workspace_id}/playground-session"
        assert client.put(path, headers=org).status_code == 200

        ended = client.delete(path, headers=org)
        assert ended.status_code == 200
        assert ended.json()["data"] == {"status": "ended"}
        assert 'airllm_playground=""' in ended.headers["set-cookie"]
        bundle = BundleV1.model_validate(client.get("/api/v1/bundle/latest", headers=org).json()["data"])
        assert bundle.keys == []


def test_playground_session_requires_execute_permission(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        org_id = make_org(client, root)
        org = cp.headers(org_id)
        workspace_id = make_workspace(client, org)
        path = f"/api/v1/orgs/{org_id}/workspaces/{workspace_id}/playground-session"
        reader = cp.headers(org_id, permissions=[Permission.catalog_read])

        assert client.put(path, headers=reader).status_code == 403
