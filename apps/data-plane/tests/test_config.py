from __future__ import annotations

import pytest

from data_plane.config import load_config

CONFIG_YML = """
data_plane:
  control_plane:
    url: http://cp.internal:9000
  bundle:
    public_key: env:MY_PUBLIC_KEY
    cache_dir: /var/cache/from-file
    poll_interval_s: 7
  auth:
    token_public_key: env:MY_PUBLIC_KEY
"""


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for var in ("MY_PUBLIC_KEY", "GW_CONFIG", "GW_DEV"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def test_config_file_with_env_secret_from_dotenv(clean_env):
    (clean_env / "airllm.yml").write_text(CONFIG_YML, encoding="utf-8")
    (clean_env / ".env").write_text("MY_PUBLIC_KEY=resolved-from-dotenv\n", encoding="utf-8")
    config = load_config()
    assert config.bundle.public_key == "resolved-from-dotenv"
    assert config.control_plane.url == "http://cp.internal:9000"
    assert config.bundle.poll_interval_s == 7.0
    assert str(config.bundle.cache_dir) == "/var/cache/from-file"


def test_console_env_wins_over_dotenv_for_refs(clean_env, monkeypatch):
    (clean_env / "airllm.yml").write_text(CONFIG_YML, encoding="utf-8")
    (clean_env / ".env").write_text("MY_PUBLIC_KEY=from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("MY_PUBLIC_KEY", "from-console")
    assert load_config().bundle.public_key == "from-console"


def test_gw_config_selects_the_file(clean_env, monkeypatch):
    (clean_env / "other.yml").write_text(CONFIG_YML, encoding="utf-8")
    monkeypatch.setenv("MY_PUBLIC_KEY", "resolved")
    monkeypatch.setenv("GW_CONFIG", str(clean_env / "other.yml"))
    assert load_config().control_plane.url == "http://cp.internal:9000"


def test_defaults_apply_for_missing_sections(clean_env, monkeypatch):
    (clean_env / "airllm.yml").write_text("data_plane:\n  bundle:\n    public_key: pk\n  auth:\n    token_public_key: pk\n", encoding="utf-8")
    config = load_config()
    assert config.control_plane.url is None
    assert config.bundle.poll_interval_s == 30.0
    assert config.events.flush_interval_s == 5.0
    assert config.bundle.staleness_policy == "serve_and_warn"
