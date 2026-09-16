from __future__ import annotations

import json
import stat
import sys

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from cli.main import app, main
from cli.profiles import (
    CliConfig,
    InvalidConfigError,
    Profile,
    config_path,
    load_active_profile,
    load_config,
    remove_profile,
    set_active,
    upsert_profile,
    upsert_url_profile,
)

runner = CliRunner()


def test_profile_config_rejects_invalid_known_fields(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(path))
    path.write_text('[profiles.acme]\nscope = "instance"\ntoken = 7\n', encoding="utf-8")
    with pytest.raises(InvalidConfigError, match=r"profiles\.acme\.token: Input should be a valid string") as raised:
        load_config()
    assert "token = 7" not in str(raised.value)


def test_cli_reports_invalid_config_without_a_traceback_or_secrets(tmp_path, monkeypatch, capsys):
    path = tmp_path / "config.toml"
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(path))
    path.write_text('[profiles.acme]\ntoken = "secret-token"\n', encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["airmux", "status"])
    with pytest.raises(SystemExit) as raised:
        main()
    output = capsys.readouterr()

    assert raised.value.code == 1
    assert str(path) in output.err
    assert "profiles.acme.scope: Field required" in output.err
    assert "Fix or move this file, then retry" in output.err
    assert "Traceback" not in output.err
    assert "secret-token" not in output.err


@pytest.mark.parametrize(
    "profile",
    [
        {"token": "missing-scope"},
        {"scope": "org", "token": "missing-organization"},
        {"scope": "instance", "org_id": "not-valid-here", "token": "instance"},
    ],
)
def test_profile_states_are_structural(profile):
    with pytest.raises(ValidationError):
        CliConfig.model_validate({"profiles": {"test": profile}})


def test_profile_round_trip_and_permissions(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(tmp_path / "config.toml"))
    assert load_config() == CliConfig()
    assert load_active_profile() is None

    upsert_profile("acme", Profile(scope="org", control_plane_url="http://cp:8000", org_id="o1", org_name="acme", token="sk-cp-x"))
    upsert_profile("beta", Profile(scope="org", control_plane_url="http://cp:8000", org_id="o2", org_name="beta", token="sk-cp-y"))

    latest = load_active_profile()
    assert latest is not None
    assert load_config().active == "beta"
    set_active("acme")
    profile = load_active_profile()
    assert profile is not None
    assert load_config().active == "acme"
    assert profile.token == "sk-cp-x"

    mode = stat.S_IMODE(config_path().stat().st_mode)
    assert mode == 0o600


def test_config_rejects_unknown_settings(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(path))
    path.write_text('[settings]\ncolor = "never"\n', encoding="utf-8")
    with pytest.raises(InvalidConfigError, match="settings: Extra inputs are not permitted"):
        load_config()


def test_url_profile_updates_the_same_name_on_the_same_deployment(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(tmp_path / "config.toml"))
    first = {
        "control_plane_url": "https://airmux.example.com",
        "scope": "org",
        "org_id": "org-1",
        "org_name": "michel",
        "token": "old",
    }
    replacement = {**first, "control_plane_url": "https://airmux.example.com/", "token": "new"}

    assert upsert_url_profile("michel", Profile.model_validate(first)) == "michel"
    assert upsert_url_profile("michel", Profile.model_validate(replacement)) == "michel"
    assert load_config().profiles == {"michel": Profile.model_validate(replacement)}


def test_url_profile_keeps_the_same_name_on_different_deployments(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(tmp_path / "config.toml"))
    local = {"control_plane_url": "http://127.0.0.1:8000", "scope": "org", "org_id": "org-1", "org_name": "michel", "token": "local"}
    fly = {"control_plane_url": "https://airmux-example.fly.dev", "scope": "org", "org_id": "org-1", "org_name": "michel", "token": "fly"}

    assert upsert_url_profile("michel", Profile.model_validate(local)) == "michel"
    assert upsert_url_profile("michel", Profile.model_validate(fly)) == "michel@airmux-example.fly.dev"
    set_active("michel")
    assert upsert_url_profile("michel", Profile.model_validate({**fly, "token": "fly-new"})) == "michel@airmux-example.fly.dev"

    config = load_config()
    assert config.active == "michel@airmux-example.fly.dev"
    assert config.profiles["michel"].token == "local"
    assert config.profiles["michel@airmux-example.fly.dev"].token == "fly-new"


def test_instance_profile_does_not_replace_an_organization_named_instance(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(tmp_path / "config.toml"))
    organization = {
        "control_plane_url": "https://airmux.example.com",
        "scope": "org",
        "org_id": "org-1",
        "org_name": "instance",
        "token": "org",
    }
    instance = {
        "control_plane_url": "https://airmux.example.com",
        "scope": "instance",
        "token": "instance",
    }

    assert upsert_url_profile("instance", Profile.model_validate(organization)) == "instance"
    assert upsert_url_profile("instance", Profile.model_validate(instance)) == "instance@airmux.example.com"
    assert len(load_config().profiles) == 2


def test_profile_selection_rejects_an_unknown_name(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(tmp_path / "config.toml"))

    with pytest.raises(KeyError):
        set_active("missing")


def test_removing_the_active_profile_selects_the_next_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(tmp_path / "config.toml"))
    upsert_profile("acme", Profile(scope="instance", token="first"))
    upsert_profile("beta", Profile(scope="instance", token="second"))

    remove_profile("beta")

    profile = load_active_profile()
    assert profile is not None
    assert load_config().active == "acme"
    assert profile.token == "first"


def test_profile_commands_are_discoverable_and_never_print_tokens(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(tmp_path / "config.toml"))
    upsert_profile(
        "acme",
        Profile(
            scope="org",
            control_plane_url="https://airmux.example.com",
            gateway_url="https://gateway.example.com",
            org_id="org-1",
            org_name="Acme",
            workspace="production",
            token="secret-token",
        ),
    )

    listed = runner.invoke(app, ["profiles", "list", "-f", "json"])
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.stdout) == [
        {
            "active": True,
            "name": "acme",
            "scope": "org",
            "organization": "Acme",
            "workspace": "production",
            "control_plane_url": "https://airmux.example.com",
            "gateway_url": "https://gateway.example.com",
        }
    ]
    assert "secret-token" not in listed.stdout

    removed = runner.invoke(app, ["profiles", "remove", "acme"])
    assert removed.exit_code == 0, removed.output
    assert load_active_profile() is None
