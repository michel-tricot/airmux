from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from contract import private_key_to_b64
from control_plane.config import DEFAULT_DATABASE_URL, database_url, load_settings


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


DATABASE_SECTION = "control_plane:\n  database:\n    url: ${env:DATABASE_URL}\n"


def test_database_url_comes_from_the_environment(tmp_path, monkeypatch):
    (tmp_path / "airllm.yml").write_text(DATABASE_SECTION, encoding="utf-8")
    monkeypatch.setenv("GW_CONFIG", str(tmp_path / "airllm.yml"))
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://someone:secret@db.example:5432/app")

    assert database_url() == "postgresql+asyncpg://someone:secret@db.example:5432/app"


def test_unset_database_url_leaves_the_local_default(tmp_path, monkeypatch):
    """An unresolved ref is the same situation as no key at all, so a checkout without the variable still runs."""
    (tmp_path / "airllm.yml").write_text(DATABASE_SECTION, encoding="utf-8")
    monkeypatch.setenv("GW_CONFIG", str(tmp_path / "airllm.yml"))
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert database_url() == DEFAULT_DATABASE_URL


def test_a_managed_url_gains_the_async_driver(tmp_path, monkeypatch):
    """Replit and friends hand out postgresql:// URLs; every engine here is async."""
    (tmp_path / "airllm.yml").write_text(DATABASE_SECTION, encoding="utf-8")
    monkeypatch.setenv("GW_CONFIG", str(tmp_path / "airllm.yml"))
    monkeypatch.setenv("DATABASE_URL", "postgresql://someone:secret@db.example:5432/app")

    assert database_url() == "postgresql+asyncpg://someone:secret@db.example:5432/app"


def test_settings_read_the_same_database_url(tmp_path, monkeypatch):
    """load_settings and database_url are two doors onto one value and must not disagree."""
    key = private_key_to_b64(Ed25519PrivateKey.generate())
    config = f'{DATABASE_SECTION}  bundle:\n    signing_key: "{key}"\n'
    (tmp_path / "airllm.yml").write_text(config, encoding="utf-8")
    monkeypatch.setenv("GW_CONFIG", str(tmp_path / "airllm.yml"))
    monkeypatch.setenv("DATABASE_URL", "postgres://someone:secret@db.example:5432/app")

    assert load_settings().database.url == "postgresql+asyncpg://someone:secret@db.example:5432/app"
