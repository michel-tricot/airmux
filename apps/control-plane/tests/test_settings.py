from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from contract import private_key_to_b64
from control_plane.config import database_url, load_settings


def test_load_settings_resolves_refs(tmp_path, monkeypatch):
    bundle_key_b64 = private_key_to_b64(Ed25519PrivateKey.generate())
    (tmp_path / "bundle.key").write_text(bundle_key_b64, encoding="utf-8")
    config = (
        "control_plane:\n  database:\n    url: postgresql+asyncpg://cp:cp@127.0.0.1:5432/cp\n"
        f"  bundle:\n    signing_key: file:{tmp_path}/bundle.key\n"
    )
    (tmp_path / "airllm.yml").write_text(config, encoding="utf-8")
    monkeypatch.setenv("GW_CONFIG", str(tmp_path / "airllm.yml"))

    settings = load_settings()
    assert settings.database.url == "postgresql+asyncpg://cp:cp@127.0.0.1:5432/cp"
    assert private_key_to_b64(settings.bundle.signing_key) == bundle_key_b64
    assert settings.dev is False


def test_malformed_signing_key_fails_at_load(tmp_path, monkeypatch):
    config = 'control_plane:\n  bundle:\n    signing_key: "not-a-key"\n'
    (tmp_path / "airllm.yml").write_text(config, encoding="utf-8")
    monkeypatch.setenv("GW_CONFIG", str(tmp_path / "airllm.yml"))
    with pytest.raises((ValidationError, ValueError)):
        load_settings()


def test_dev_flag_comes_from_the_environment(tmp_path, monkeypatch):
    key = private_key_to_b64(Ed25519PrivateKey.generate())
    config = f'control_plane:\n  bundle:\n    signing_key: "{key}"\n'
    (tmp_path / "airllm.yml").write_text(config, encoding="utf-8")
    monkeypatch.setenv("GW_CONFIG", str(tmp_path / "airllm.yml"))
    monkeypatch.setenv("GW_DEV", "1")
    assert load_settings().dev is True


def test_database_url_falls_back_without_a_config_file(tmp_path, monkeypatch):
    monkeypatch.setenv("GW_CONFIG", str(tmp_path / "missing.yml"))
    assert database_url() == "postgresql+asyncpg://airllm:airllm@127.0.0.1:5432/airllm"
