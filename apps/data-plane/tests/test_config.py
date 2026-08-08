from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from contract import DEFAULT_CONFIG_YML, public_key_to_b64, uuid7
from data_plane.config import load_config

TEMPLATE_ORG = uuid7()
PUBLIC_KEY_B64 = public_key_to_b64(Ed25519PrivateKey.generate().public_key())
OTHER_KEY_B64 = public_key_to_b64(Ed25519PrivateKey.generate().public_key())

CONFIG_YML = """
data_plane:
  control_plane:
    url: http://cp.internal:9000
  bundle:
    public_key: env:MY_PUBLIC_KEY
    cache_dir: /var/cache/from-file
    poll_interval_s: 7
"""


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for var in ("MY_PUBLIC_KEY", "GW_CONFIG", "GW_DEV"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def test_config_file_with_env_secret_from_dotenv(clean_env):
    (clean_env / "airllm.yml").write_text(CONFIG_YML, encoding="utf-8")
    (clean_env / ".env").write_text(f"MY_PUBLIC_KEY={PUBLIC_KEY_B64}\n", encoding="utf-8")
    config = load_config()
    assert public_key_to_b64(config.bundle.public_key) == PUBLIC_KEY_B64
    assert config.control_plane.url == "http://cp.internal:9000"
    assert config.bundle.poll_interval_s == 7.0
    assert str(config.bundle.cache_dir) == "/var/cache/from-file"


def test_console_env_wins_over_dotenv_for_refs(clean_env, monkeypatch):
    (clean_env / "airllm.yml").write_text(CONFIG_YML, encoding="utf-8")
    (clean_env / ".env").write_text(f"MY_PUBLIC_KEY={OTHER_KEY_B64}\n", encoding="utf-8")
    monkeypatch.setenv("MY_PUBLIC_KEY", PUBLIC_KEY_B64)
    assert public_key_to_b64(load_config().bundle.public_key) == PUBLIC_KEY_B64


def test_gw_config_selects_the_file(clean_env, monkeypatch):
    (clean_env / "other.yml").write_text(CONFIG_YML, encoding="utf-8")
    monkeypatch.setenv("MY_PUBLIC_KEY", PUBLIC_KEY_B64)
    monkeypatch.setenv("GW_CONFIG", str(clean_env / "other.yml"))
    assert load_config().control_plane.url == "http://cp.internal:9000"


def test_shared_config_template_parses_through_the_data_plane_loader(clean_env, monkeypatch):
    rendered = DEFAULT_CONFIG_YML.format(
        db_url="postgresql+asyncpg://airllm:airllm@127.0.0.1:5432/airllm",
        control_plane_url="http://127.0.0.1:8000",
        org=str(TEMPLATE_ORG),
        cache_dir=".airllm",
    )
    (clean_env / "airllm.yml").write_text(rendered, encoding="utf-8")
    monkeypatch.setenv("GW_DATAPLANE_TOKEN", "dp-token")
    monkeypatch.setenv("GW_BUNDLE_PUBLIC_KEY", PUBLIC_KEY_B64)
    config = load_config()
    assert config.control_plane.url == "http://127.0.0.1:8000"
    assert config.control_plane.token == "dp-token"
    assert config.bundle.org == TEMPLATE_ORG
    assert public_key_to_b64(config.bundle.public_key) == PUBLIC_KEY_B64
    assert str(config.bundle.cache_dir) == ".airllm"


def test_malformed_public_key_fails_at_load(clean_env):
    (clean_env / "airllm.yml").write_text(CONFIG_YML, encoding="utf-8")
    (clean_env / ".env").write_text("MY_PUBLIC_KEY=not-a-key\n", encoding="utf-8")
    with pytest.raises((ValidationError, ValueError)):
        load_config()


def test_defaults_apply_for_missing_sections(clean_env, monkeypatch):
    config = f"data_plane:\n  bundle:\n    public_key: {PUBLIC_KEY_B64}\n"
    (clean_env / "airllm.yml").write_text(config, encoding="utf-8")
    config = load_config()
    assert config.control_plane.url is None
    assert config.bundle.poll_interval_s == 30.0
    assert config.events.flush_interval_s == 5.0
    assert config.bundle.staleness_policy == "serve_and_warn"
