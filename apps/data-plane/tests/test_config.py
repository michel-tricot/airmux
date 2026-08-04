from __future__ import annotations

import pytest

from data_plane.config import load_config

CONFIG_YML = """
data_plane:
  control_plane_url: http://cp.internal:9000
  bundle_public_key: env:MY_PUBLIC_KEY
  cache_dir: /var/cache/from-file
  poll_interval_s: 7
"""


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for var in ("GW_BUNDLE_PUBLIC_KEY", "GW_CACHE_DIR", "GW_CONTROL_PLANE_URL", "GW_POLL_INTERVAL_S", "GW_CONFIG"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def test_env_file_loaded_from_cwd(clean_env):
    (clean_env / ".env").write_text("GW_BUNDLE_PUBLIC_KEY=from-dotenv\nGW_CACHE_DIR=/var/cache/from-dotenv\n", encoding="utf-8")
    config = load_config()
    assert config.bundle_public_key_b64 == "from-dotenv"
    assert str(config.cache_dir) == "/var/cache/from-dotenv"


def test_console_env_wins_over_env_file(clean_env, monkeypatch):
    monkeypatch.setenv("GW_BUNDLE_PUBLIC_KEY", "from-console")
    (clean_env / ".env").write_text("GW_BUNDLE_PUBLIC_KEY=from-dotenv\n", encoding="utf-8")
    assert load_config().bundle_public_key_b64 == "from-console"


def test_config_file_with_env_secret_resolution(clean_env):
    (clean_env / "airllm.yml").write_text(CONFIG_YML, encoding="utf-8")
    (clean_env / ".env").write_text("MY_PUBLIC_KEY=resolved-from-dotenv\n", encoding="utf-8")
    config = load_config()
    assert config.bundle_public_key_b64 == "resolved-from-dotenv"
    assert config.control_plane_url == "http://cp.internal:9000"
    assert str(config.cache_dir) == "/var/cache/from-file"
    assert config.poll_interval_s == 7.0


def test_env_var_wins_over_config_file(clean_env, monkeypatch):
    (clean_env / "airllm.yml").write_text(CONFIG_YML, encoding="utf-8")
    (clean_env / ".env").write_text("MY_PUBLIC_KEY=resolved\n", encoding="utf-8")
    monkeypatch.setenv("GW_POLL_INTERVAL_S", "3")
    assert load_config().poll_interval_s == 3.0


def test_gw_config_selects_the_file(clean_env, monkeypatch):
    (clean_env / "other.yml").write_text(CONFIG_YML, encoding="utf-8")
    (clean_env / ".env").write_text("MY_PUBLIC_KEY=resolved\n", encoding="utf-8")
    monkeypatch.setenv("GW_CONFIG", str(clean_env / "other.yml"))
    assert load_config().control_plane_url == "http://cp.internal:9000"
