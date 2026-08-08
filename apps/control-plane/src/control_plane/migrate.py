from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine


def _config() -> AlembicConfig:
    ini = Path(__file__).resolve().parents[2] / "alembic.ini"
    cfg = AlembicConfig(str(ini))
    cfg.set_main_option("script_location", str(ini.parent / "migrations"))
    return cfg


def run_migrations() -> None:
    command.upgrade(_config(), "head")


def head_revision() -> str | None:
    """The newest revision in the migration scripts; what an up-to-date database is stamped with."""
    return ScriptDirectory.from_config(_config()).get_current_head()


def current_revision(database_url: str) -> str | None:
    """The revision the database is stamped with; None when it has never been migrated."""

    async def read() -> str | None:
        engine = create_async_engine(database_url)
        try:
            async with engine.connect() as conn:
                return (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one_or_none()
        except ProgrammingError:
            return None
        finally:
            await engine.dispose()

    return asyncio.run(read())
