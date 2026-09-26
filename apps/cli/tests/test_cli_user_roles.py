from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest
import respx
from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


@pytest.mark.parametrize("role", ["owner", "auditor", "data_plane", "none"])
@respx.mock
def test_instance_role_command_reports_the_updated_role(tmp_path, monkeypatch, role):
    user_id = str(uuid4())
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("AIRMUX_MANAGEMENT_KEY", "sk-test-roles")
    monkeypatch.setenv("AIRMUX_CONTROL_PLANE_URL", "http://cp.test")

    def change_role(request):
        assigned_role = None if role == "none" else role
        assert json.loads(request.content) == {"instance_role": assigned_role}
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": user_id,
                    "email": "user@example.com",
                    "name": "User",
                    "instance_role": assigned_role,
                    "service_account": False,
                    "managing_org_id": None,
                    "orgs": [],
                    "created_at": "2026-09-25T00:00:00Z",
                    "updated_at": "2026-09-25T00:00:00Z",
                }
            },
        )

    respx.put(f"http://cp.test/api/v1/users/{user_id}/instance-role").mock(side_effect=change_role)
    result = runner.invoke(app, ["users", "role", user_id, role, "-f", "json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)[0]["instance_role"] == (None if role == "none" else role)


def test_instance_role_command_rejects_unknown_roles():
    result = runner.invoke(app, ["users", "role", str(uuid4()), "admin"])
    assert result.exit_code == 2
    assert "Invalid value" in result.output


@respx.mock
def test_user_show_lists_direct_roles_at_every_scope(tmp_path, monkeypatch):
    user_id, org_id, workspace_id = (str(uuid4()) for _ in range(3))
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("AIRMUX_MANAGEMENT_KEY", "sk-test-roles")
    monkeypatch.setenv("AIRMUX_CONTROL_PLANE_URL", "http://cp.test")
    respx.get(f"http://cp.test/api/v1/users/{user_id}").respond(
        200,
        json={
            "data": {
                "id": user_id,
                "email": "user@example.com",
                "name": "User",
                "instance_role": "auditor",
                "service_account": False,
                "managing_org_id": None,
                "orgs": [org_id],
                "created_at": "2026-09-25T00:00:00Z",
                "updated_at": "2026-09-25T00:00:00Z",
            }
        },
    )
    respx.get(f"http://cp.test/api/v1/users/{user_id}/memberships").respond(
        200,
        json={
            "data": {
                "org_memberships": [{"org_id": org_id, "name": "Acme", "role": "member"}],
                "workspace_memberships": [
                    {"workspace_id": workspace_id, "org_id": org_id, "name": "Production", "slug": "production", "role": "viewer"}
                ],
            }
        },
    )
    result = runner.invoke(app, ["users", "show", user_id, "-f", "json"])
    assert result.exit_code == 0, result.output
    assert [(assignment["scope"], assignment["id"], assignment["role"]) for assignment in json.loads(result.stdout)] == [
        ("instance", user_id, "auditor"),
        ("organization", org_id, "member"),
        ("workspace", workspace_id, "viewer"),
    ]


@pytest.mark.parametrize("scope", ["orgs", "workspaces"])
@respx.mock
def test_membership_upsert_reports_the_assigned_role(tmp_path, monkeypatch, scope):
    user_id, org_id, workspace_id = (str(uuid4()) for _ in range(3))
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("AIRMUX_MANAGEMENT_KEY", "sk-test-roles")
    monkeypatch.setenv("AIRMUX_CONTROL_PLANE_URL", "http://cp.test")
    monkeypatch.setenv("AIRMUX_ORG_ID", org_id)
    membership = {"user_id": user_id, "org_id": org_id, "role": "admin", "status": "member"}
    if scope == "workspaces":
        membership = {
            **membership,
            "workspace_id": workspace_id,
            "email": "user@example.com",
            "name": "User",
            "service_account": False,
        }
    path = f"/api/v1/organizations/{org_id}" + (f"/workspaces/production/members/{user_id}" if scope == "workspaces" else f"/users/{user_id}")
    respx.put(f"http://cp.test{path}").respond(200, json={"data": membership})
    command = [scope, "members", "add", user_id, "--role", "admin", "-f", "json"]
    if scope == "workspaces":
        command += ["--workspace", "production"]
    result = runner.invoke(app, command)
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)[0]["role"] == "admin"
