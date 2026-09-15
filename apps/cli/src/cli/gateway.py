from __future__ import annotations

from pathlib import Path
from shlex import quote as shell_quote
from typing import Annotated

import typer

from cli.common import gateway_app
from cli.runtime import ConfigOption, DirectoryOption, HostOption, PortOption, configuration_path, runtime_command


@gateway_app.command()
@runtime_command("gateway")
def init(
    taxonomy: Annotated[
        Path, typer.Option("--taxonomy", exists=True, dir_okay=False, readable=True, help="Existing provider and model taxonomy YAML")
    ],
    directory: DirectoryOption = Path(),
) -> None:
    """Create standalone configuration and a private inference key."""
    from data_plane.setup import initialize  # noqa: PLC0415 load the optional runtime only when its command runs

    initialize(directory, taxonomy)
    typer.echo(f"Created {directory / 'tokkeeper.yml'} and {directory / '.tokkeeper/inference.key'}")
    typer.echo("Set your provider environment variables, such as OPENAI_API_KEY")
    typer.echo(f"Start with: tokkeeper gateway serve --config {shell_quote(str(directory / 'tokkeeper.yml'))}")


@gateway_app.command()
@runtime_command("gateway")
def validate(config: ConfigOption = None) -> None:
    """Check configuration and local bundle admission without contacting providers."""
    from data_plane.setup import validate_configuration  # noqa: PLC0415 load the optional runtime only when its command runs

    path = configuration_path(config, "gateway")
    validate_configuration(path)
    typer.echo(f"Gateway configuration is valid: {path}")
    typer.echo("Provider credentials, connectivity, and remote bundles are verified when serving")


@gateway_app.command()
@runtime_command("gateway")
def serve(
    config: ConfigOption = None,
    host: HostOption = "127.0.0.1",
    port: PortOption = 8080,
    dev: Annotated[bool, typer.Option("--dev", help="Reload Python code during development")] = False,
    workers: Annotated[int, typer.Option("--workers", min=1, help="Worker processes sharing one gateway state directory")] = 1,
) -> None:
    """Run the inference gateway in the foreground."""
    from data_plane.operations import serve as serve_gateway  # noqa: PLC0415 load the optional runtime only when its command runs
    from data_plane.setup import validate_configuration  # noqa: PLC0415 load the optional runtime only when its command runs

    if dev and workers != 1:
        message = "--dev requires --workers 1"
        raise typer.BadParameter(message)
    path = configuration_path(config, "gateway")
    validate_configuration(path)
    serve_gateway(path, host=host, port=port, dev=dev, workers=workers)


@gateway_app.command()
@runtime_command("gateway")
def schema(
    out: Annotated[Path, typer.Option("--out", help="Directory for the canonical request, response, and stream schemas")] = Path(
        "taxonomy/schemas/completion"
    ),
) -> None:
    """Export the canonical inference JSON schemas."""
    from data_plane.operations import export_schema  # noqa: PLC0415 load the optional runtime only when its command runs

    export_schema(out)
    typer.echo(f"Wrote inference schemas to {out}")
