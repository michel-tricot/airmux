"""Which control plane and console the CLI talks to, and how --dev shortcuts them."""

from __future__ import annotations

import pytest

from cli.auth import DEFAULT_CONSOLE_URL, resolve_urls
from cli.client import LOCAL_CONTROL_PLANE_URL, resolve_control_plane_url
from cli.common import invocation


@pytest.fixture(autouse=True)
def _plain_invocation():
    """--dev is state for the whole run, so a test that sets it has to put it back."""
    invocation.dev = False
    yield
    invocation.dev = False


@pytest.fixture
def _no_ambient_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GW_CONTROL_PLANE_URL", raising=False)
    monkeypatch.setenv("GW_CLI_CONFIG", str(tmp_path / "config.toml"))


@pytest.mark.usefixtures("_no_ambient_config")
def test_dev_names_the_local_control_plane():
    invocation.dev = True

    assert resolve_control_plane_url() == LOCAL_CONTROL_PLANE_URL


@pytest.mark.usefixtures("_no_ambient_config")
def test_an_explicit_url_beats_dev():
    """The flag is a shortcut, not an override of what the caller actually asked for."""
    invocation.dev = True

    assert resolve_control_plane_url("https://cp.example.com") == "https://cp.example.com"


def test_dev_beats_a_stored_profile(tmp_path, monkeypatch):
    """A development run must not be redirected by whatever org the machine last logged into."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GW_CONTROL_PLANE_URL", raising=False)
    monkeypatch.setenv("GW_CLI_CONFIG", str(tmp_path / "config.toml"))
    from cli.profiles import set_active, upsert_profile  # noqa: PLC0415 the profile has to be written under the patched path

    upsert_profile("prod", {"control_plane_url": "https://prod.example.com", "token": "t"})
    set_active("prod")

    assert resolve_control_plane_url() == "https://prod.example.com"
    invocation.dev = True
    assert resolve_control_plane_url() == LOCAL_CONTROL_PLANE_URL


@pytest.mark.usefixtures("_no_ambient_config")
def test_the_console_does_not_move_with_dev():
    """One console port everywhere, so the flag has nothing to switch."""
    invocation.dev = True

    assert resolve_urls("", "") == (LOCAL_CONTROL_PLANE_URL, DEFAULT_CONSOLE_URL)


@pytest.mark.usefixtures("_no_ambient_config")
def test_explicit_urls_win_over_everything():
    invocation.dev = True

    assert resolve_urls("https://cp.example.com", "https://console.example.com") == (
        "https://cp.example.com",
        "https://console.example.com",
    )


def test_a_checkout_config_is_not_a_source(tmp_path, monkeypatch):
    """airllm.yml configures the servers, not the CLI. Reading it would point a run at whatever
    checkout it happened to start in rather than at the deployment the user signed into."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GW_CONTROL_PLANE_URL", raising=False)
    monkeypatch.setenv("GW_CLI_CONFIG", str(tmp_path / "config.toml"))
    (tmp_path / "airllm.yml").write_text("data_plane:\n  control_plane:\n    url: http://somewhere.else:9999\n", encoding="utf-8")

    assert resolve_control_plane_url() == LOCAL_CONTROL_PLANE_URL
