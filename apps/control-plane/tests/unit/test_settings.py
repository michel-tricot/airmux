from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from contract import FileStoreConfig
from control_plane.config import (
    DEFAULT_CONSOLE_URL,
    DEFAULT_DATABASE_URL,
    DataPlaneBootstrap,
    database_url,
    load_settings,
)

DATABASE_SECTION = f"control_plane:\n  database:\n    url: ${{env:DATABASE_URL:-{DEFAULT_DATABASE_URL}}}\n"


def test_database_url_falls_back_without_a_config_file(tmp_path, monkeypatch):
    monkeypatch.setenv("GW_CONFIG", str(tmp_path / "missing.yml"))
    assert database_url() == "postgresql+asyncpg://airllm:airllm@127.0.0.1:5432/airllm"


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


def test_settings_read_the_same_database_url(tmp_path, monkeypatch):
    """load_settings and database_url are two doors onto one value and must not disagree."""
    (tmp_path / "airllm.yml").write_text(DATABASE_SECTION, encoding="utf-8")
    monkeypatch.setenv("GW_CONFIG", str(tmp_path / "airllm.yml"))
    monkeypatch.setenv("DATABASE_URL", "postgres://someone:secret@db.example:5432/app")

    assert load_settings().database.url == "postgresql+asyncpg://someone:secret@db.example:5432/app"


def test_the_shipped_config_loads_with_and_without_a_database_url(tmp_path, monkeypatch):
    """The config the repo ships has to keep parsing; nothing else guards an edit to it.

    The mirror of the data plane's loader test. Composing the url from unset variables broke this
    without any suite noticing, because the control plane had no such test.
    """
    repo_config = Path(__file__).resolve().parents[4] / "airllm.yml"
    monkeypatch.chdir(tmp_path)
    (tmp_path / "airllm.yml").write_text(repo_config.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.delenv("GW_CONFIG", raising=False)

    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert database_url() == DEFAULT_DATABASE_URL

    monkeypatch.setenv("DATABASE_URL", "postgresql://someone:secret@db.example:5432/app")
    assert database_url() == "postgresql+asyncpg://someone:secret@db.example:5432/app"


def test_the_shipped_config_serves_the_checkout_and_the_stack(tmp_path, monkeypatch):
    """One config file covers both deployments, so the values that differ have to move with the environment.

    A checkout gets the local console and the pool key deployment tooling wrote; compose sets the variables and
    gets the containerized ones, from the same file.
    """
    repo_config = Path(__file__).resolve().parents[4] / "airllm.yml"
    monkeypatch.chdir(tmp_path)
    (tmp_path / "airllm.yml").write_text(repo_config.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / ".airllm").mkdir()
    token = "sk-cp-one-shared-pool-secret-that-is-long-enough"
    (tmp_path / ".airllm" / "dataplane.key").write_text(token, encoding="utf-8")
    monkeypatch.delenv("GW_CONFIG", raising=False)

    for var in ("DATABASE_URL", "GW_CONSOLE_URL"):
        monkeypatch.delenv(var, raising=False)
    checkout = load_settings()
    assert checkout.console_url == DEFAULT_CONSOLE_URL
    assert checkout.database.url == DEFAULT_DATABASE_URL
    assert checkout.bootstrap == DataPlaneBootstrap(token=token)

    monkeypatch.setenv("GW_CONSOLE_URL", "http://localhost:3000")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://airllm:airllm@postgres:5432/airllm")
    stack = load_settings()
    assert stack.console_url == "http://localhost:3000"
    assert stack.database.url == "postgresql+asyncpg://airllm:airllm@postgres:5432/airllm"


def test_container_config_uses_shared_credentials_and_separate_secret_storage(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[4] / "deploy" / "docker" / "control-plane.yml"
    container_config = tmp_path / "control-plane.yml"
    container_config.write_text(source.read_text().replace("/state/", f"{tmp_path}/"))
    cache_dir = tmp_path / "runtime"
    cache_dir.mkdir()
    token = "sk-cp-one-shared-pool-secret-that-is-long-enough"
    (cache_dir / "dataplane.key").write_text(token, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql://someone:secret@db.internal:5432/app")
    monkeypatch.setenv("GW_CONSOLE_URL", "https://console.example.com")

    settings = load_settings(container_config)

    assert settings.database.url == "postgresql+asyncpg://someone:secret@db.internal:5432/app"
    assert settings.console_url == "https://console.example.com"
    assert settings.secrets == FileStoreConfig(root=tmp_path / "secrets")
    assert settings.bootstrap == DataPlaneBootstrap(token=token)


def test_supplied_bootstrap_token_is_validated_and_redacted():
    token = "sk-cp-one-shared-pool-secret-that-is-long-enough"
    bootstrap = DataPlaneBootstrap(token=token)

    assert token not in repr(bootstrap)
    with pytest.raises(ValidationError, match="complete access key"):
        DataPlaneBootstrap(token="not-an-access-key")


def test_the_fly_migration_config_uses_the_direct_database_url(monkeypatch):
    migration_config = Path(__file__).resolve().parents[4] / "deploy" / "docker" / "migrate-fly.yml"
    monkeypatch.setenv("GW_CONFIG", str(migration_config))
    monkeypatch.setenv("DIRECT_DATABASE_URL", "postgresql://someone:secret@direct.db.internal:5432/app")

    assert database_url() == "postgresql+asyncpg://someone:secret@direct.db.internal:5432/app"
