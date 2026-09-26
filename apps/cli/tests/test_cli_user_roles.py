from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest
import respx
from click import unstyle
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


@pytest.mark.parametrize(
    ("scope", "role"),
    [
        ("orgs", "owner"),
        ("orgs", "admin"),
        ("orgs", "member"),
        ("orgs", "data_plane"),
        ("workspaces", "admin"),
        ("workspaces", "member"),
        ("workspaces", "viewer"),
    ],
)
@pytest.mark.parametrize("command_name", ["add", "role"])
@respx.mock
def test_membership_role_command_reports_the_updated_role(tmp_path, monkeypatch, scope, role, command_name):
    user_id, org_id, workspace_id = (str(uuid4()) for _ in range(3))
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("AIRMUX_MANAGEMENT_KEY", "sk-test-roles")
    monkeypatch.setenv("AIRMUX_CONTROL_PLANE_URL", "http://cp.test")
    monkeypatch.setenv("AIRMUX_ORG_ID", org_id)
    membership = {"user_id": user_id, "org_id": org_id, "role": role, "status": "member"}
    if scope == "workspaces":
        membership = {**membership, "workspace_id": workspace_id, "email": "user@example.com", "name": "User", "service_account": False}
    path = f"/api/v1/organizations/{org_id}" + (f"/workspaces/production/members/{user_id}" if scope == "workspaces" else f"/users/{user_id}")

    def change_role(request):
        assert json.loads(request.content) == {"role": role}
        return httpx.Response(200, json={"data": membership})

    respx.put("http://cp.test" + path).mock(side_effect=change_role)
    command = [scope, "members", command_name, user_id, "--role", role, "-f", "json"]
    if scope == "workspaces":
        command += ["--workspace", "production"]
    result = runner.invoke(app, command)
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)[0]["role"] == role


@pytest.mark.parametrize(("scope", "role"), [("orgs", "viewer"), ("workspaces", "owner")])
def test_membership_role_command_rejects_roles_from_other_scopes(scope, role):
    result = runner.invoke(app, [scope, "members", "role", str(uuid4()), "--role", role])
    assert result.exit_code == 2
    assert "Invalid value" in result.output


@pytest.mark.parametrize("scope", ["orgs", "workspaces"])
@respx.mock
def test_membership_role_command_requires_an_explicit_role(scope):
    result = runner.invoke(app, [scope, "members", "role", str(uuid4())])
    assert result.exit_code == 2
    assert "Missing option" in result.output
    assert "--role" in unstyle(result.output)
