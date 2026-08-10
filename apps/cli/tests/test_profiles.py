from __future__ import annotations

import stat

from cli.profiles import active_profile, admin_keys_url, config_path, load_config, set_active, upsert_profile


def test_profile_round_trip_and_permissions(tmp_path, monkeypatch):
    monkeypatch.setenv("GW_CLI_CONFIG", str(tmp_path / "config.toml"))
    assert load_config() == {}
    assert active_profile() is None

    upsert_profile("acme", {"control_plane_url": "http://cp:8000", "org_id": "o1", "org_name": "acme", "token": "sk-mgmt-x"})
    upsert_profile("beta", {"control_plane_url": "http://cp:8000", "org_id": "o2", "org_name": "beta", "token": "sk-mgmt-y"})

    latest = active_profile()
    assert latest is not None
    assert latest["name"] == "beta"
    set_active("acme")
    profile = active_profile()
    assert profile is not None
    assert profile["name"] == "acme"
    assert profile["token"] == "sk-mgmt-x"

    mode = stat.S_IMODE(config_path().stat().st_mode)
    assert mode == 0o600


def test_upsert_preserves_unknown_settings(tmp_path, monkeypatch):
    """The config is a home for future settings, not just tokens; writes must not drop what they do not know."""
    path = tmp_path / "config.toml"
    monkeypatch.setenv("GW_CLI_CONFIG", str(path))
    path.write_text('[settings]\ncolor = "never"\n', encoding="utf-8")
    upsert_profile("acme", {"token": "t"})
    assert load_config()["settings"] == {"color": "never"}


def test_admin_keys_url_points_at_the_console_you_signed_into(tmp_path, monkeypatch):
    """The commands that refuse for want of an admin key have no credential to ask anything with,
    so the page that mints one has to come from what login already recorded."""
    monkeypatch.setenv("GW_CLI_CONFIG", str(tmp_path / "config.toml"))
    upsert_profile("acme", {"console_url": "https://console.acme.test", "token": "t"})
    set_active("acme")

    assert admin_keys_url() == "https://console.acme.test/instance/keys"


def test_admin_keys_url_falls_back_when_nobody_signed_in(tmp_path, monkeypatch):
    monkeypatch.setenv("GW_CLI_CONFIG", str(tmp_path / "config.toml"))

    assert admin_keys_url() == "http://localhost:3000/instance/keys"
