from __future__ import annotations

import os
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

import typer
import yaml
from pydantic import ValidationError

from contract import UnknownVarError

if TYPE_CHECKING:
    from collections.abc import Callable

Runtime = Literal["gateway", "control-plane"]
ConfigOption = Annotated[Path | None, typer.Option("--config", "-c", help="Configuration file; defaults to TOKKEEPER_CONFIG or ./tokkeeper.yml")]
DirectoryOption = Annotated[Path, typer.Option("--directory", "-d", help="Configuration directory; existing files are never overwritten")]
PortOption = Annotated[int, typer.Option("--port", min=1, max=65535, help="Port to listen on")]
HostOption = Annotated[str, typer.Option("--host", help="Address to listen on")]


def runtime_command[**P](command: Callable[P, None]) -> Callable[P, None]:
    @wraps(command)
    def invoke(*args: P.args, **kwargs: P.kwargs) -> None:
        try:
            command(*args, **kwargs)
        except ValidationError as error:
            details = "; ".join(f"{'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}" for issue in error.errors(include_input=False))
            typer.echo(f"Error: Invalid configuration: {details}", err=True)
            raise typer.Exit(1) from None
        except yaml.YAMLError as error:
            location = getattr(error, "problem_mark", None)
            detail = f" at line {location.line + 1}" if location else ""
            typer.echo(f"Error: Invalid YAML{detail}; check the configuration file", err=True)
            raise typer.Exit(1) from None
        except (OSError, TypeError, ValueError, UnknownVarError) as error:
            typer.echo(f"Error: {error}", err=True)
            raise typer.Exit(1) from None

    return invoke


def configuration_path(config: Path | None, runtime: Runtime) -> Path:
    path = (config or Path(os.environ.get("TOKKEEPER_CONFIG", "tokkeeper.yml"))).expanduser().resolve()
    if not path.is_file():
        message = f"Configuration file not found: {path}. Run 'tokkeeper {runtime} init' or provide --config PATH"
        raise ValueError(message)
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    section = "data_plane" if runtime == "gateway" else "control_plane"
    if not isinstance(document, dict) or not isinstance(document.get(section), dict):
        message = f"{path} must contain a {section} section"
        raise TypeError(message)
    return path
