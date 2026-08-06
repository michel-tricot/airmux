from __future__ import annotations

from pathlib import Path

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from contract import DEFAULT_CONFIG_YML, private_key_to_b64
from control_plane.config import load_settings

RENDERED = DEFAULT_CONFIG_YML.format(
    db_url="sqlite+aiosqlite:///airllm.db",
    control_plane_url="http://127.0.0.1:8000",
    org="org-dev",
    cache_dir=".airllm",
)


def test_default_config_matches_repo_airllm_yml():
    repo = yaml.safe_load((Path(__file__).parents[3] / "airllm.yml").read_text(encoding="utf-8"))
    assert yaml.safe_load(RENDERED) == repo


def test_template_parses_through_control_plane_settings(tmp_path, monkeypatch):
    cfg = tmp_path / "airllm.yml"
    cfg.write_text(RENDERED, encoding="utf-8")
    token_key = private_key_to_b64(Ed25519PrivateKey.generate())
    bundle_key = private_key_to_b64(Ed25519PrivateKey.generate())
    monkeypatch.setenv("GW_TOKEN_SIGNING_KEY", token_key)
    monkeypatch.setenv("GW_BUNDLE_SIGNING_KEY", bundle_key)
    monkeypatch.delenv("GW_DEV", raising=False)
    settings = load_settings(cfg)
    assert settings.database.url == "sqlite+aiosqlite:///airllm.db"
    assert private_key_to_b64(settings.auth.token_signing_key) == token_key
    assert private_key_to_b64(settings.bundle.signing_key) == bundle_key
