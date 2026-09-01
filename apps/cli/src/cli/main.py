from __future__ import annotations

from cli import auth, commands, diagnostics, resources  # noqa: F401 importing registers the commands on the shared app
from cli.common import app

__all__ = ["app"]
