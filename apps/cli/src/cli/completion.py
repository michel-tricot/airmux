from __future__ import annotations

from typing import Annotated, Literal

import typer
from typer.completion import install

from cli.common import GOODIES, app

Shell = Literal["bash", "zsh", "fish", "powershell", "pwsh"]


@app.command(rich_help_panel=GOODIES)
def completion(
    shell: Annotated[Shell | None, typer.Option("--shell", help="Shell to configure; detected automatically by default")] = None,
) -> None:
    """Install shell completion for TokKeeper commands."""
    installed_shell, path = install(shell=shell, prog_name="tokkeeper", complete_var="_TOKKEEPER_COMPLETE")
    typer.echo(f"Installed {installed_shell} completion at {path}")
    typer.echo("Restart your shell to use it")
