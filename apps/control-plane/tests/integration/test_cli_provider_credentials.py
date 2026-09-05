from __future__ import annotations

import asyncio
import json
from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient
from helpers import MODEL, PROVIDER, make_org, setup_control_plane
from typer.testing import CliRunner

from cli.main import app as cli_app
from contract import SecretPurpose, SecretRef

KEY = "sk-provider-abcd1234"


runner = CliRunner()


@pytest.fixture
def cli(tmp_path, monkeypatch):
    """A booted control plane with the CLI pointed at it, plus an org, a workspace, and a catalog.

    _bearer_client is the one seam: every command builds its client through it, so replacing it with
    one that speaks to the app in-process leaves the commands themselves untouched. A TestClient is
    what stands in, because the commands are synchronous and an ASGI transport is not.
    """
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        c.post("/api/v1/instance/taxonomy/providers", json=PROVIDER, headers=root)
        c.post("/api/v1/instance/taxonomy/models", json=MODEL, headers=root)
        org_id = make_org(c, root)
        org = cp.headers(org_id)
        c.headers.update(org)
        workspace = c.post(f"/api/v1/orgs/{org_id}/workspaces", json={"name": "Staging"}, headers=org).json()["data"]

        def _client(token: str, control_plane_url: str):
            return nullcontext(c)

        monkeypatch.setattr("cli.client._bearer_client", _client)
        monkeypatch.setenv("AIRLLM_CLI_CONFIG", str(tmp_path / "config.toml"))
        monkeypatch.setenv("AIRLLM_ACCESS_KEY", org["authorization"].removeprefix("Bearer "))
        monkeypatch.setenv("AIRLLM_ORG_ID", str(org_id))
        yield cp, workspace["slug"]


def run(*args, stdin: str | None = None):
    result = runner.invoke(cli_app, list(args), input=stdin)
    assert result.exit_code == 0, result.output
    return result.output


def stored(cp, credential: dict) -> str:
    ref = SecretRef(
        purpose=SecretPurpose.provider,
        service=credential["provider_name"],
        name=credential["name"],
        secret_id=credential["id"],
        org_id=credential["org_id"],
        workspace_id=credential["workspace_id"],
    )
    return asyncio.run(cp.app.state.secret_store.get(ref)).reveal()


def listed(cp, workspace: str) -> list[dict]:
    """What the list command prints as json, which is the shape a script would consume."""
    return json.loads(run("provider-credentials", "list", "--workspace", workspace, "-f", "json"))


def test_a_piped_key_never_reaches_the_command_line(cli):
    """The reason there is no --value flag: an automated caller pipes, and the key stays out of the
    shell history and out of every other user's view of the process list."""
    cp, workspace = cli
    output = run("provider-credentials", "add", "openai", "--workspace", workspace, stdin=f"{KEY}\n")
    assert KEY not in output
    assert "...1234" in output
    credential = listed(cp, workspace)[0]
    assert stored(cp, credential) == KEY


def test_the_listing_names_the_provider_and_the_key_health(cli):
    """A listing of uuids and booleans is not one anyone can act on: the credential carries the
    provider it was written under, and enabled folds into health because a disabled key is out of
    the pool regardless of what its last request said."""
    cp, workspace = cli
    run("provider-credentials", "add", "openai", "--workspace", workspace, stdin=f"{KEY}\n")
    credential = listed(cp, workspace)[0]
    assert credential["provider_name"] == "openai"
    assert credential["health"] == "unused"
    assert credential["fingerprint"] == "1234"
    assert KEY not in run("provider-credentials", "list", "--workspace", workspace)


def test_a_disabled_key_reads_as_disabled_whatever_its_last_request_said(cli):
    cp, workspace = cli
    run("provider-credentials", "add", "openai", "--workspace", workspace, stdin=f"{KEY}\n")
    run("provider-credentials", "disable", listed(cp, workspace)[0]["id"])
    assert listed(cp, workspace)[0]["health"] == "disabled"


def test_a_pool_lists_in_the_order_the_data_plane_tries_it(cli):
    cp, workspace = cli
    run("provider-credentials", "add", "openai", "--workspace", workspace, "--name", "backup", "--priority", "200", stdin="sk-b\n")
    run("provider-credentials", "add", "openai", "--workspace", workspace, "--name", "primary", "--priority", "10", stdin="sk-a\n")
    assert [c["name"] for c in listed(cp, workspace)] == ["primary", "backup"]


def test_rotate_replaces_the_value_and_keeps_the_place(cli):
    cp, workspace = cli
    run("provider-credentials", "add", "openai", "--workspace", workspace, stdin=f"{KEY}\n")
    credential = listed(cp, workspace)[0]
    output = run("provider-credentials", "rotate", credential["id"], stdin="sk-rotated-9999\n")
    assert "...9999" in output
    assert stored(cp, credential) == "sk-rotated-9999"
    assert listed(cp, workspace)[0]["version"] == 2


def test_disable_takes_a_key_out_of_the_pool_without_deleting_it(cli):
    cp, workspace = cli
    run("provider-credentials", "add", "openai", "--workspace", workspace, stdin=f"{KEY}\n")
    credential = listed(cp, workspace)[0]
    run("provider-credentials", "disable", credential["id"])
    assert listed(cp, workspace)[0]["enabled"] is False
    run("provider-credentials", "disable", credential["id"], "--enable")
    assert listed(cp, workspace)[0]["enabled"] is True


def test_rm_deletes_the_credential(cli):
    cp, workspace = cli
    run("provider-credentials", "add", "openai", "--workspace", workspace, stdin=f"{KEY}\n")
    credential = listed(cp, workspace)[0]
    run("provider-credentials", "rm", credential["id"])
    assert listed(cp, workspace) == []


def test_an_org_wide_key_is_not_scoped_to_a_workspace(cli):
    cp, _ = cli
    run("provider-credentials", "add", "openai", "--org", stdin=f"{KEY}\n")
    credential = json.loads(run("provider-credentials", "list", "--org", "-f", "json"))[0]
    assert credential["scope"] == "org"
    assert credential["workspace_id"] is None
    assert stored(cp, credential) == KEY
