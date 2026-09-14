from __future__ import annotations

import typer

from cli import (  # noqa: F401 importing registers the commands on the shared app
    auth,
    commands,
    control_plane,
    diagnostics,
    gateway,
    policies,
    resources,
    rules,
)
from cli.common import app
from cli.profiles import InvalidConfigError


def main() -> None:
    try:
        app()
    except InvalidConfigError as error:
        typer.echo(f"Error: {error}", err=True)
        raise SystemExit(1) from None


__all__ = ["app", "main"]
