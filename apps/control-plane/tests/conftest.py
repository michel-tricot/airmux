"""One throwaway Postgres server per pytest run, shared by every test and xdist worker.

pytest_configure runs in the xdist controller before workers spawn, so the container is started
exactly once and its admin URL reaches the workers through the environment. The template
database is built by the alembic chain, so every test runs against exactly the schema a
deployment has; test_schema owns proving that create_all and the models agree with it. Tests
clone the template per tmp_path through pg.py. Set AIRLLM_TEST_PG_URL to reuse a long-lived
local server and skip the container start.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pg import ADMIN_URL_ENV, TEMPLATE_DB, db_name_for, drop_database, url_for
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.core.container import DockerContainer

CONTROL_PLANE_DIR = Path(__file__).resolve().parents[1]

PG_IMAGE = "postgres:18"
PG_COMMAND = "postgres -c fsync=off -c synchronous_commit=off -c full_page_writes=off"

_container_key: pytest.StashKey[DockerContainer] = pytest.StashKey()


def pytest_configure(config: pytest.Config) -> None:
    if hasattr(config, "workerinput") or ADMIN_URL_ENV in os.environ:
        return
    os.environ[ADMIN_URL_ENV] = _start_server(config)
    _build_template()


def pytest_unconfigure(config: pytest.Config) -> None:
    container = config.stash.get(_container_key, None)
    if container is not None:
        container.stop()


def _start_server(config: pytest.Config) -> str:
    container = (
        DockerContainer(PG_IMAGE)
        .with_env("POSTGRES_USER", "test")
        .with_env("POSTGRES_PASSWORD", "test")
        .with_env("POSTGRES_DB", "postgres")
        .with_command(PG_COMMAND)
        .with_exposed_ports(5432)
        .with_tmpfs_mount("/var/lib/postgresql")
    )
    container.start()
    config.stash[_container_key] = container
    url = f"postgresql+asyncpg://test:test@{container.get_container_host_ip()}:{container.get_exposed_port(5432)}/postgres"
    _wait_ready(url)
    return url


def _wait_ready(url: str, timeout: float = 30.0) -> None:
    """A real connection, not pg_isready: initdb briefly runs a throwaway server that answers probes."""

    async def ping() -> None:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        finally:
            await engine.dispose()

    deadline = time.monotonic() + timeout
    while True:
        try:
            asyncio.run(ping())
        except (OSError, DBAPIError):
            if time.monotonic() > deadline:
                raise
            time.sleep(0.2)
        else:
            return


def _build_template() -> None:
    """Migrate an empty template from scratch every run: an external server may hold one from an older schema."""

    async def recreate() -> None:
        admin = create_async_engine(os.environ[ADMIN_URL_ENV], isolation_level="AUTOCOMMIT")
        try:
            async with admin.connect() as conn:
                await conn.execute(text(f'DROP DATABASE IF EXISTS "{TEMPLATE_DB}" WITH (FORCE)'))
                await conn.execute(text(f'CREATE DATABASE "{TEMPLATE_DB}"'))
        finally:
            await admin.dispose()

    asyncio.run(recreate())
    config = Config(str(CONTROL_PLANE_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(CONTROL_PLANE_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", url_for(TEMPLATE_DB))
    command.upgrade(config, "head")


@pytest.fixture(autouse=True)
def _test_database(tmp_path: Path):
    yield
    drop_database(db_name_for(tmp_path))
