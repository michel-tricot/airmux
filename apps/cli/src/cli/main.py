from __future__ import annotations

from cli import auth, commands, resources, testing  # noqa: F401 importing registers the commands on the shared app
from cli.common import app

__all__ = ["app"]
