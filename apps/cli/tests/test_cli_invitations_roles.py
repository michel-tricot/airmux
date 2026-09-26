from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from typer.testing import CliRunner

from cli import client, resources
from cli.main import app

runner = CliRunner()


def test_invitation_commands_use_the_active_org_and_show_a_link_only_when_minted(monkeypatch):
    org_id = uuid4()
    invitation_id = uuid4()
    now = datetime.now(tz=UTC).isoformat()
    requests: list[tuple[str, str, dict | None]] = []
    invitation = {
        "id": str(invitation_id),
        "org_id": str(org_id),
        "email": "person@example.com",
        "org_role": "member",
        "workspace_id": None,
        "workspace_role": None,
        "created_by_user_id": None,
        "expires_at": now,
        "accepted_at": None,
        "accepted_by_user_id": None,
        "revoked_at": None,
        "created_at": now,
        "updated_at": now,
        "status": "pending",
    }

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        requests.append((request.method, request.url.path, body))
        data = (
            [invitation]
            if request.method == "GET"
            else {"id": str(invitation_id), "status": "revoked", "revoked_at": now}
            if request.url.path.endswith("/revoke")
            else {"invitation": invitation, "url": "https://console.example/invite#token=secret"}
        )
        return httpx.Response(200, request=request, json={"data": data})

    monkeypatch.setenv("AIRMUX_ORG_ID", str(org_id))

    def access_client(_url: str) -> httpx.Client:
        return httpx.Client(base_url="http://control-plane", transport=httpx.MockTransport(respond))

    monkeypatch.setattr(resources, "access_client", access_client)
    monkeypatch.setattr(client, "access_client", access_client)

    created = runner.invoke(app, ["orgs", "invitations", "create", "person@example.com", "-f", "json"])
    listed = runner.invoke(app, ["orgs", "invitations", "list", "-f", "json"])
    reissued = runner.invoke(app, ["orgs", "invitations", "reissue", str(invitation_id), "-f", "json"])
    revoked = runner.invoke(app, ["orgs", "invitations", "revoke", str(invitation_id), "-f", "json"])

    assert all(result.exit_code == 0 for result in (created, listed, reissued, revoked))
    assert json.loads(created.stdout)[0]["url"].endswith("token=secret")
    assert "url" not in json.loads(listed.stdout)[0]
    assert json.loads(reissued.stdout)[0]["url"].endswith("token=secret")
    assert json.loads(revoked.stdout)[0]["status"] == "revoked"
    base = f"/api/v1/organizations/{org_id}/invitations"
    assert requests == [
        ("POST", base, {"email": "person@example.com", "org_role": "member", "workspace_id": None, "workspace_role": None}),
        ("GET", base, None),
        ("POST", f"{base}/{invitation_id}/reissue", None),
        ("POST", f"{base}/{invitation_id}/revoke", None),
    ]


def test_role_commands_target_each_scope_and_decode_the_response(monkeypatch):
    org_id = uuid4()
    user_id = uuid4()
    workspace_id = uuid4()
    now = datetime.now(tz=UTC).isoformat()
    requests: list[tuple[str, dict]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append((request.url.path, body))
        if request.url.path.endswith("/instance-role"):
            data = {
                "id": str(user_id),
                "email": "person@example.com",
                "name": "Person",
                "instance_role": body["instance_role"],
                "service_account": False,
                "managing_org_id": None,
                "created_at": now,
                "updated_at": now,
                "orgs": [str(org_id)],
            }
        elif "/workspaces/" in request.url.path:
            data = {
                "user_id": str(user_id),
                "workspace_id": str(workspace_id),
                "email": "person@example.com",
                "name": "Person",
                "service_account": False,
                "role": body["role"],
                "status": "member",
            }
        else:
            data = {"user_id": str(user_id), "org_id": str(org_id), "role": body["role"], "status": "member"}
        return httpx.Response(200, request=request, json={"data": data})

    monkeypatch.setenv("AIRMUX_ORG_ID", str(org_id))

    def access_client(_url: str) -> httpx.Client:
        return httpx.Client(base_url="http://control-plane", transport=httpx.MockTransport(respond))

    monkeypatch.setattr(resources, "access_client", access_client)
    instance = runner.invoke(app, ["users", "set-role", str(user_id), "owner", "-f", "json"])
    cleared = runner.invoke(app, ["users", "set-role", str(user_id), "none", "-f", "json"])
    organization = runner.invoke(app, ["orgs", "members", "set-role", str(user_id), "admin", "-f", "json"])
    workspace = runner.invoke(app, ["workspaces", "members", "set-role", str(user_id), "viewer", "--workspace", str(workspace_id), "-f", "json"])

    assert all(result.exit_code == 0 for result in (instance, cleared, organization, workspace))
    assert json.loads(instance.stdout)[0]["instance_role"] == "owner"
    assert json.loads(cleared.stdout)[0]["instance_role"] is None
    assert json.loads(organization.stdout)[0]["role"] == "admin"
    assert json.loads(workspace.stdout)[0]["role"] == "viewer"
    assert requests == [
        (f"/api/v1/users/{user_id}/instance-role", {"instance_role": "owner"}),
        (f"/api/v1/users/{user_id}/instance-role", {"instance_role": None}),
        (f"/api/v1/organizations/{org_id}/users/{user_id}", {"role": "admin"}),
        (f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/members/{user_id}", {"role": "viewer"}),
    ]


def test_invitation_grants_require_a_complete_workspace_pair(monkeypatch):
    workspace_id = uuid4()
    submitted: list[dict] = []

    def respond(request: httpx.Request) -> httpx.Response:
        submitted.append(json.loads(request.content))
        return httpx.Response(409, request=request, json={"detail": "A pending invitation already exists for this email"})

    monkeypatch.setenv("AIRMUX_ORG_ID", str(uuid4()))
    monkeypatch.setattr(
        resources,
        "access_client",
        lambda _url: httpx.Client(base_url="http://control-plane", transport=httpx.MockTransport(respond)),
    )

    incomplete = runner.invoke(app, ["orgs", "invitations", "create", "person@example.com", "--workspace", str(workspace_id)])
    invalid_role = runner.invoke(app, ["orgs", "invitations", "create", "person@example.com", "--role", "owner"])
    complete = runner.invoke(
        app,
        ["orgs", "invitations", "create", "person@example.com", "--workspace", str(workspace_id), "--workspace-role", "viewer"],
    )

    assert incomplete.exit_code == 1
    assert "must be provided together" in incomplete.output
    assert invalid_role.exit_code == 2
    assert complete.exit_code == 1
    assert "pending invitation already exists" in complete.output
    assert submitted == [{"email": "person@example.com", "org_role": "member", "workspace_id": str(workspace_id), "workspace_role": "viewer"}]
