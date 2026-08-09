"""Which control plane and console quickstart talks to, and how --dev shortcuts them."""

from __future__ import annotations

import pytest

from cli.auth import DEFAULT_CONSOLE_URL, DEV_CONSOLE_URL, DEV_CONTROL_PLANE_URL, resolve_urls


@pytest.fixture(autouse=True)
def _no_ambient_url(monkeypatch, tmp_path):
    """Resolution reads the environment, the active profile and airllm.yml; this test is about the flags."""
    monkeypatch.delenv("GW_CONTROL_PLANE_URL", raising=False)
    monkeypatch.setenv("GW_CLI_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("GW_CONFIG", str(tmp_path / "airllm.yml"))
    monkeypatch.chdir(tmp_path)


def test_dev_points_at_the_local_pair():
    assert resolve_urls("", "", dev=True) == (DEV_CONTROL_PLANE_URL, DEV_CONSOLE_URL)


def test_without_dev_the_console_default_is_the_served_one():
    control_plane, console = resolve_urls("", "", dev=False)
    assert console == DEFAULT_CONSOLE_URL
    assert control_plane == "http://127.0.0.1:8000"


def test_explicit_flags_win_over_dev():
    assert resolve_urls("https://cp.example.com", "https://console.example.com", dev=True) == (
        "https://cp.example.com",
        "https://console.example.com",
    )


def test_dev_beats_an_ambient_control_plane_url(monkeypatch):
    """A stale profile or env var is exactly what --dev is for; it does not get to win."""
    monkeypatch.setenv("GW_CONTROL_PLANE_URL", "https://prod.example.com")
    assert resolve_urls("", "", dev=True)[0] == DEV_CONTROL_PLANE_URL
    assert resolve_urls("", "", dev=False)[0] == "https://prod.example.com"
