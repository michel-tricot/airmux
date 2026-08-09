from __future__ import annotations

from pathlib import Path

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


DATABASE_SECTION = f"control_plane:\n  database:\n    url: ${{env:DATABASE_URL:-{DEFAULT_DATABASE_URL}}}\n"


def test_database_url_comes_from_the_environment(tmp_path, monkeypatch):
    (tmp_path / "airllm.yml").write_text(DATABASE_SECTION, encoding="utf-8")
    monkeypatch.setenv("GW_CONFIG", str(tmp_path / "airllm.yml"))
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://someone:secret@db.example:5432/app")

    assert database_url() == "postgresql+asyncpg://someone:secret@db.example:5432/app"


def test_unset_database_url_leaves_the_local_default(tmp_path, monkeypatch):
    """The :- default in the config file is what keeps a checkout without the variable running."""
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


def test_a_managed_url_translates_libpq_sslmode_for_asyncpg(tmp_path, monkeypatch):
    (tmp_path / "airllm.yml").write_text(DATABASE_SECTION, encoding="utf-8")
    monkeypatch.setenv("GW_CONFIG", str(tmp_path / "airllm.yml"))
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://someone:secret@db.example:5432/app?sslmode=require&application_name=airllm",
    )

    assert database_url() == (
        "postgresql+asyncpg://someone:secret@db.example:5432/app"
        "?ssl=require&application_name=airllm"
    )


def test_settings_read_the_same_database_url(tmp_path, monkeypatch):
    """load_settings and database_url are two doors onto one value and must not disagree."""
    key = private_key_to_b64(Ed25519PrivateKey.generate())
    config = f'{DATABASE_SECTION}  bundle:\n    signing_key: "{key}"\n'
    (tmp_path / "airllm.yml").write_text(config, encoding="utf-8")
    monkeypatch.setenv("GW_CONFIG", str(tmp_path / "airllm.yml"))
    monkeypatch.setenv("DATABASE_URL", "postgres://someone:secret@db.example:5432/app")

    assert load_settings().database.url == "postgresql+asyncpg://someone:secret@db.example:5432/app"


def test_the_shipped_config_loads_with_and_without_a_database_url(tmp_path, monkeypatch):
    """The config the repo ships has to keep parsing; nothing else guards an edit to it.

    The mirror of the data plane's loader test. Composing the url from unset variables broke this
    without any suite noticing, because the control plane had no such test.
    """
    repo_config = Path(__file__).resolve().parents[3] / "airllm.yml"
    monkeypatch.chdir(tmp_path)
    (tmp_path / "airllm.yml").write_text(repo_config.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.delenv("GW_CONFIG", raising=False)

    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert database_url() == DEFAULT_DATABASE_URL

    monkeypatch.setenv("DATABASE_URL", "postgresql://someone:secret@db.example:5432/app")
    assert database_url() == "postgresql+asyncpg://someone:secret@db.example:5432/app"
