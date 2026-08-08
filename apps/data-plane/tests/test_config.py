from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from contract import DEFAULT_CONFIG_YML, public_key_to_b64, uuid7
from data_plane.config import load_config

TEMPLATE_ORG = uuid7()
PUBLIC_KEY_B64 = public_key_to_b64(Ed25519PrivateKey.generate().public_key())


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for var in ("GW_CONFIG", "GW_DEV"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


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
    (clean_env / "airllm.yml").write_text("data_plane:\n  bundle:\n    public_key: not-a-key\n", encoding="utf-8")
    with pytest.raises((ValidationError, ValueError)):
        load_config()


def test_defaults_apply_for_missing_sections(clean_env):
    config = f"data_plane:\n  bundle:\n    public_key: {PUBLIC_KEY_B64}\n"
    (clean_env / "airllm.yml").write_text(config, encoding="utf-8")
    config = load_config()
    assert config.control_plane.url is None
    assert config.bundle.poll_interval_s == 30.0
    assert config.events.flush_interval_s == 5.0
    assert config.bundle.staleness_policy == "serve_and_warn"
