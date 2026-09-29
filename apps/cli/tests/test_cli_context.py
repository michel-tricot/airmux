from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest
import respx
import typer
from pydantic import ValidationError
from typer.testing import CliRunner

from cli.client import resolve_org_id, resolve_workspace
from cli.main import app
from cli.profiles import CliConfig, Profile, load_config, save_config, upsert_profile

runner = CliRunner()


def test_selected_target_is_independent_of_instance_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(tmp_path / "config.toml"))
    upsert_profile("instance", Profile(scope="instance", token="instance-key"))
    save_config(load_config().model_copy(update={"org_id": "org-a", "workspace": "production"}))

    assert resolve_org_id() == "org-a"
    assert resolve_workspace("") == "production"
    assert load_config().profiles["instance"].workspace is None


@pytest.mark.parametrize(
    ("selection", "message"),
    [
        ({"workspace": "production"}, "selected workspace requires an organization"),
        ({"org_name": "Acme"}, "selected organization name requires an organization"),
        ({"workspace_name": "Production"}, "selected workspace name requires a workspace"),
    ],
)
def test_config_rejects_incomplete_selection(selection, message):
    with pytest.raises(ValidationError, match=message):
        CliConfig.model_validate(selection)


def test_workspace_default_cannot_cross_organization_override(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(tmp_path / "config.toml"))
    save_config(CliConfig(org_id="org-a", workspace="production"))
    monkeypatch.setenv("AIRMUX_ORGANIZATION_ID", "org-b")

    with pytest.raises(typer.Exit):
        resolve_workspace("")
    assert "belongs to another organization" in capsys.readouterr().out
    assert resolve_workspace("staging") == "staging"


def test_profile_workspace_cannot_cross_organization_override(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(tmp_path / "config.toml"))
    upsert_profile("acme", Profile(scope="org", org_id="org-a", org_name="Acme", workspace="production"))
    monkeypatch.setenv("AIRMUX_ORGANIZATION_ID", "org-b")

    with pytest.raises(typer.Exit):
        resolve_workspace("")
    assert "profile workspace belongs to another organization" in capsys.readouterr().out


def test_organization_target_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(tmp_path / "config.toml"))
    upsert_profile("profile", Profile(scope="org", org_id="profile-org", org_name="Profile"))
    assert resolve_org_id() == "profile-org"

    save_config(load_config().model_copy(update={"org_id": "saved-org"}))
    assert resolve_org_id() == "saved-org"

    monkeypatch.setenv("AIRMUX_ORGANIZATION_ID", "environment-org")
    assert resolve_org_id() == "environment-org"
    assert resolve_org_id("explicit-org") == "explicit-org"


@respx.mock
def test_selecting_org_and_workspace_keeps_instance_credentials(tmp_path, monkeypatch):
    org_id, workspace_id = (str(uuid4()) for _ in range(2))
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("AIRMUX_CONTROL_PLANE_URL", "http://cp.test")
    upsert_profile("instance", Profile(scope="instance", token="instance-key"))
    now = "2026-09-08T00:00:00Z"
    organization = {"id": org_id, "name": "Acme", "slug": "acme", "personal_for": None, "created_at": now, "updated_at": now}
    workspace = {"id": workspace_id, "org_id": org_id, "name": "Production", "slug": "production", "created_at": now, "updated_at": now}
    org_route = respx.get(f"http://cp.test/api/v1/organizations/{org_id}").mock(return_value=httpx.Response(200, json={"data": organization}))
    workspace_route = respx.get(f"http://cp.test/api/v1/organizations/{org_id}/workspaces/production").mock(
        return_value=httpx.Response(200, json={"data": workspace})
    )

    selected_org = runner.invoke(app, ["organizations", "switch", org_id])
    selected_workspace = runner.invoke(app, ["workspaces", "use", "production"])

    assert selected_org.exit_code == selected_workspace.exit_code == 0
    assert org_route.calls[0].request.headers["authorization"] == "Bearer instance-key"
    assert workspace_route.calls[0].request.headers["authorization"] == "Bearer instance-key"
    assert load_config().active == "instance"
    assert load_config().org_id == org_id
    assert load_config().workspace == "production"
    assert load_config().profiles["instance"].workspace is None


@respx.mock
def test_org_switch_clears_workspace_only_after_a_valid_response(tmp_path, monkeypatch):
    org_a, org_b = (str(uuid4()) for _ in range(2))
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("AIRMUX_MANAGEMENT_KEY", "instance-key")
    monkeypatch.setenv("AIRMUX_CONTROL_PLANE_URL", "http://cp.test")
    save_config(CliConfig(org_id=org_a, workspace="production"))
    route = respx.get(f"http://cp.test/api/v1/organizations/{org_b}").mock(return_value=httpx.Response(404, json={"detail": "Not found"}))

    invalid = runner.invoke(app, ["organizations", "switch", org_b])
    assert invalid.exit_code == 1
    assert load_config().org_id == org_a
    assert load_config().workspace == "production"

    now = "2026-09-08T00:00:00Z"
    route.mock(
        return_value=httpx.Response(
            200,
            json={"data": {"id": org_b, "name": "Beta", "slug": "beta", "personal_for": None, "created_at": now, "updated_at": now}},
        )
    )
    valid = runner.invoke(app, ["organizations", "switch", org_b])
    assert valid.exit_code == 0, valid.output
    assert load_config().org_id == org_b
    assert load_config().workspace is None


def test_status_reports_conflicting_environment_org(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(tmp_path / "config.toml"))
    save_config(CliConfig(org_id="org-a", workspace="production"))
    monkeypatch.setenv("AIRMUX_ORGANIZATION_ID", "org-b")

    status = runner.invoke(app, ["status", "-f", "json"])
    assert status.exit_code == 0, status.output
    assert json.loads(status.stdout)[0]["organization"] == "org-b"
    assert "conflict" in json.loads(status.stdout)[0]["workspace"]


@respx.mock
def test_workspace_selection_rejects_mismatched_response_before_config_write(tmp_path, monkeypatch):
    org_a, org_b, workspace_id = (str(uuid4()) for _ in range(3))
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("AIRMUX_MANAGEMENT_KEY", "instance-key")
    monkeypatch.setenv("AIRMUX_CONTROL_PLANE_URL", "http://cp.test")
    save_config(CliConfig(org_id=org_a))
    now = "2026-09-08T00:00:00Z"
    workspace = {"id": workspace_id, "org_id": org_b, "name": "Production", "slug": "production", "created_at": now, "updated_at": now}
    respx.get(f"http://cp.test/api/v1/organizations/{org_a}/workspaces/production").mock(return_value=httpx.Response(200, json={"data": workspace}))

    result = runner.invoke(app, ["workspaces", "use", "production"])

    assert result.exit_code == 1
    assert "another organization" in result.output
    assert load_config().workspace is None


@respx.mock
def test_policy_toggle_accepts_explicit_target_and_reports_state(tmp_path, monkeypatch):
    org_id, workspace_id, policy_id = (str(uuid4()) for _ in range(3))
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("AIRMUX_MANAGEMENT_KEY", "instance-key")
    monkeypatch.setenv("AIRMUX_ORGANIZATION_ID", str(uuid4()))
    monkeypatch.setenv("AIRMUX_CONTROL_PLANE_URL", "http://cp.test")
    policy = {
        "id": policy_id,
        "org_id": org_id,
        "workspace_id": workspace_id,
        "name": "Production",
        "enabled": False,
        "definition": {
            "target": {"kind": "workspace"},
            "rules": [{"match": {"kind": "all_requests"}, "action": {"kind": "request_limits", "max_output_tokens": 2048}}],
        },
        "created_at": "2026-09-08T00:00:00Z",
        "updated_at": "2026-09-08T00:00:00Z",
    }

    def respond(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {"enabled": False}
        return httpx.Response(200, json={"data": policy})

    endpoint = f"http://cp.test/api/v1/organizations/{org_id}/workspaces/production/policies/{policy_id}"
    respx.patch(endpoint).mock(side_effect=respond)
    result = runner.invoke(app, ["policies", "disable", policy_id, "--organization", org_id, "--workspace", "production", "-f", "json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)[0]["enabled"] is False


@pytest.mark.parametrize(
    "command",
    [
        *(("policies", command) for command in ("list", "create", "update", "delete", "enable", "disable", "status")),
        *(("workspaces", command) for command in ("list", "create", "use")),
        *(("workspaces", "members", command) for command in ("list", "add", "role", "remove")),
        *(("organizations", "members", command) for command in ("list", "add", "role", "remove")),
        *(("organizations", "invitations", command) for command in ("list", "create", "reissue", "revoke")),
        *(
            (group, command)
            for group, commands in {
                "inference-keys": ("list", "create", "revoke"),
                "provider-credentials": ("add", "list", "rotate", "remove", "enable", "disable"),
                "events": ("list", "tail"),
                "providers": ("list",),
                "models": ("list",),
                "management-keys": ("list", "create"),
            }.items()
            for command in commands
        ),
    ],
)
def test_org_scoped_commands_expose_org_option(command):
    result = runner.invoke(app, [*command, "--help"])
    assert result.exit_code == 0, result.output
    assert "--organization" in result.output
