from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig


def run_migrations() -> None:
    ini = Path(__file__).resolve().parents[2] / "alembic.ini"
    cfg = AlembicConfig(str(ini))
    cfg.set_main_option("script_location", str(ini.parent / "migrations"))
    command.upgrade(cfg, "head")
