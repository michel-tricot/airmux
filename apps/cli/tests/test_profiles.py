from __future__ import annotations

import json
import stat

import pytest
from typer.testing import CliRunner

from cli.main import app
from cli.profiles import active_profile, config_path, load_config, remove_profile, set_active, upsert_profile, upsert_url_profile

runner = CliRunner()


def test_profile_round_trip_and_permissions(tmp_path, monkeypatch):
    monkeypatch.setenv("GW_CLI_CONFIG", str(tmp_path / "config.toml"))
    assert load_config() == {}
    assert active_profile() is None

    upsert_profile("acme", {"control_plane_url": "http://cp:8000", "org_id": "o1", "org_name": "acme", "token": "sk-cp-x"})
    upsert_profile("beta", {"control_plane_url": "http://cp:8000", "org_id": "o2", "org_name": "beta", "token": "sk-cp-y"})

    latest = active_profile()
    assert latest is not None
    assert latest["name"] == "beta"
    set_active("acme")
    profile = active_profile()
    assert profile is not None
    assert profile["name"] == "acme"
    assert profile["token"] == "sk-cp-x"

    mode = stat.S_IMODE(config_path().stat().st_mode)
    assert mode == 0o600


def test_upsert_preserves_unknown_settings(tmp_path, monkeypatch):
    """The config is a home for future settings, not just tokens; writes must not drop what they do not know."""
    path = tmp_path / "config.toml"
    monkeypatch.setenv("GW_CLI_CONFIG", str(path))
    path.write_text('[settings]\ncolor = "never"\n', encoding="utf-8")
    upsert_profile("acme", {"token": "t"})
    assert load_config()["settings"] == {"color": "never"}


def test_url_profile_updates_the_same_name_on_the_same_deployment(tmp_path, monkeypatch):
    monkeypatch.setenv("GW_CLI_CONFIG", str(tmp_path / "config.toml"))
    first = {
        "control_plane_url": "https://airllm.example.com",
        "org_name": "michel",
        "token": "old",
    }
    replacement = {**first, "control_plane_url": "https://airllm.example.com/", "token": "new"}

    assert upsert_url_profile("michel", first) == "michel"
    assert upsert_url_profile("michel", replacement) == "michel"
    assert load_config()["profiles"] == {"michel": replacement}


def test_url_profile_keeps_the_same_name_on_different_deployments(tmp_path, monkeypatch):
    monkeypatch.setenv("GW_CLI_CONFIG", str(tmp_path / "config.toml"))
    local = {"control_plane_url": "http://127.0.0.1:8000", "org_name": "michel", "token": "local"}
    fly = {"control_plane_url": "https://airllm-example.fly.dev", "org_name": "michel", "token": "fly"}

    assert upsert_url_profile("michel", local) == "michel"
    assert upsert_url_profile("michel", fly) == "michel@airllm-example.fly.dev"
    set_active("michel")
    assert upsert_url_profile("michel", {**fly, "token": "fly-new"}) == "michel@airllm-example.fly.dev"

    config = load_config()
    assert config["active"] == "michel@airllm-example.fly.dev"
    assert config["profiles"]["michel"]["token"] == "local"
    assert config["profiles"]["michel@airllm-example.fly.dev"]["token"] == "fly-new"


def test_instance_profile_does_not_replace_an_organization_named_instance(tmp_path, monkeypatch):
    monkeypatch.setenv("GW_CLI_CONFIG", str(tmp_path / "config.toml"))
    organization = {
        "control_plane_url": "https://airllm.example.com",
        "scope": "org",
        "org_id": "org-1",
        "org_name": "instance",
        "token": "org",
    }
    instance = {
        "control_plane_url": "https://airllm.example.com",
        "scope": "instance",
        "token": "instance",
    }

    assert upsert_url_profile("instance", organization) == "instance"
    assert upsert_url_profile("instance", instance) == "instance@airllm.example.com"
    assert len(load_config()["profiles"]) == 2


def test_profile_selection_rejects_an_unknown_name(tmp_path, monkeypatch):
    monkeypatch.setenv("GW_CLI_CONFIG", str(tmp_path / "config.toml"))

    with pytest.raises(KeyError):
        set_active("missing")


def test_removing_the_active_profile_selects_the_next_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("GW_CLI_CONFIG", str(tmp_path / "config.toml"))
    upsert_profile("acme", {"token": "first"})
    upsert_profile("beta", {"token": "second"})

    remove_profile("beta")

    assert active_profile() == {"name": "acme", "token": "first"}


def test_profile_commands_are_discoverable_and_never_print_tokens(tmp_path, monkeypatch):
    monkeypatch.setenv("GW_CLI_CONFIG", str(tmp_path / "config.toml"))
    upsert_profile(
        "acme",
        {
            "control_plane_url": "https://airllm.example.com",
            "gateway_url": "https://gateway.example.com",
            "org_name": "Acme",
            "workspace": "production",
            "scope": "org",
            "token": "secret-token",
        },
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
            "control_plane_url": "https://airllm.example.com",
            "gateway_url": "https://gateway.example.com",
        }
    ]
    assert "secret-token" not in listed.stdout

    removed = runner.invoke(app, ["profiles", "remove", "acme"])
    assert removed.exit_code == 0, removed.output
    assert active_profile() is None
