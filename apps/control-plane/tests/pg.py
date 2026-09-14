"""Per-test database provisioning against the shared test Postgres server.

conftest.py starts one server per pytest run (in the xdist controller, so workers share it) and
publishes its admin URL through TOKKEEPER_TEST_PG_URL. Databases are cheap inside that server:
setup_control_plane clones the migrated-equivalent template; a test that needs to prove the
migration chain asks for an empty database instead. Names derive from tmp_path, so every test owns
its databases and the autouse fixture in conftest.py can drop them without bookkeeping.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

if TYPE_CHECKING:
    from pathlib import Path

ADMIN_URL_ENV = "TOKKEEPER_TEST_PG_URL"
TEMPLATE_DB = "cp_template"


def admin_url() -> str:
    url = os.environ.get(ADMIN_URL_ENV)
    if url is None:
        msg = f"no test postgres server; run under pytest (conftest starts one) or set {ADMIN_URL_ENV}"
        raise RuntimeError(msg)
    return url


def url_for(name: str) -> str:
    return admin_url().rsplit("/", 1)[0] + "/" + name


def db_name_for(tmp_path: Path) -> str:
    return f"cp_{hashlib.sha256(str(tmp_path).encode()).hexdigest()[:12]}"


def db_url_for(tmp_path: Path) -> str:
    return url_for(db_name_for(tmp_path))


def ensure_database(name: str, template: str | None = None) -> str:
    """Create the database unless it already exists; a second call keeps whatever state it has."""

    async def create() -> None:
        engine = create_async_engine(admin_url(), isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as conn:
                exists = (await conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name})).first()
                if exists is None:
                    suffix = f' TEMPLATE "{template}"' if template else ""
                    await conn.execute(text(f'CREATE DATABASE "{name}"{suffix}'))
        finally:
            await engine.dispose()

    asyncio.run(create())
    return url_for(name)


def drop_database(name: str) -> None:
    """FORCE terminates lingering pooled connections; test engines are not always disposed."""

    async def drop() -> None:
        engine = create_async_engine(admin_url(), isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as conn:
                await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        finally:
            await engine.dispose()

    asyncio.run(drop())
