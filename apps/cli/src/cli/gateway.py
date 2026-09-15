from __future__ import annotations

import json
from pathlib import Path
from shlex import quote as shell_quote
from typing import Annotated

import typer

from cli.common import gateway_app
from cli.runtime import ConfigOption, DirectoryOption, HostOption, PortOption, configuration_path, runtime_command


@gateway_app.command()
@runtime_command
def init(
    taxonomy: Annotated[
        Path | None,
        typer.Option("--taxonomy", exists=True, dir_okay=False, readable=True, help="Existing taxonomy YAML; defaults to the shipped taxonomy"),
    ] = None,
    directory: DirectoryOption = Path(".tokkeeper"),
) -> None:
    """Create standalone configuration and a private inference key."""
    from data_plane.setup import describe_configuration, initialize  # noqa: PLC0415 defer runtime imports to keep CLI startup fast

    initialize(directory, taxonomy)
    config = directory / "tokkeeper.yml"
    inference_key = directory / "inference.key"
    guide = describe_configuration(config)
    providers = tuple(provider for provider in guide.providers if provider.models)
    provider = next((provider for provider in providers if provider.configured_variable), providers[0])
    provider_variable = provider.configured_variable or provider.variables[-1]
    model_id = provider.models[0]
    model = json.dumps(model_id, ensure_ascii=False)
    body = json.dumps(
        {"model": model_id, "messages": [{"role": "user", "content": "Reply with exactly: tokkeeper ready"}]},
        separators=(",", ":"),
    )
    if taxonomy is None:
        typer.echo(f"Created {config}, {directory / 'taxonomy.yml'}, and {inference_key}")
    else:
        typer.echo(f"Created {config} and {inference_key}")
    typer.echo("Next:")
    if provider.configured_variable:
        typer.echo(f"  1. Provider key: {provider_variable} is set for {model}")
    else:
        typer.echo(f"  1. Set the provider key used by {model}:")
        typer.echo(f"     export {provider_variable}='your-provider-key'")
    typer.echo("  2. Start the gateway:")
    typer.echo(f"     tokkeeper gateway serve --config {shell_quote(str(config))}")
    typer.echo("  3. In another terminal, verify inference:")
    typer.echo(f'     export TOKKEEPER_INFERENCE_KEY="$(cat {shell_quote(str(inference_key))})"')
    typer.echo("     curl --fail http://127.0.0.1:8080/readyz")
    typer.echo("     curl --fail-with-body http://127.0.0.1:8080/inf/v1/chat/completions \\")
    typer.echo('       -H "Authorization: Bearer $TOKKEEPER_INFERENCE_KEY" \\')
    typer.echo("       -H 'Content-Type: application/json' \\")
    typer.echo("       -H 'X-Tokkeeper-Dialect: openai_native' \\")
    typer.echo(f"       -d {shell_quote(body)}")


@gateway_app.command()
@runtime_command
def validate(config: ConfigOption = None) -> None:
    """Check configuration and local bundle admission without contacting providers."""
    from data_plane.setup import validate_configuration  # noqa: PLC0415 defer runtime imports to keep CLI startup fast

    path = configuration_path(config, "gateway")
    validate_configuration(path)
    typer.echo(f"Gateway configuration is valid: {path}")
    typer.echo("A real inference request verifies provider credentials and connectivity")
    typer.echo("Remote bundles are fetched and admitted while serving")


@gateway_app.command()
@runtime_command
def serve(
    config: ConfigOption = None,
    host: HostOption = "127.0.0.1",
    port: PortOption = 8080,
    dev: Annotated[bool, typer.Option("--dev", help="Reload Python code during development")] = False,
    workers: Annotated[int, typer.Option("--workers", min=1, help="Worker processes sharing one gateway state directory")] = 1,
) -> None:
    """Run the inference gateway in the foreground."""
    from data_plane.operations import serve as serve_gateway  # noqa: PLC0415 defer runtime imports to keep CLI startup fast
    from data_plane.setup import validate_configuration  # noqa: PLC0415 defer runtime imports to keep CLI startup fast

    if dev and workers != 1:
        message = "--dev requires --workers 1"
        raise typer.BadParameter(message)
    path = configuration_path(config, "gateway")
    validate_configuration(path)
    serve_gateway(path, host=host, port=port, dev=dev, workers=workers)


@gateway_app.command()
@runtime_command
def schema(
    out: Annotated[Path, typer.Option("--out", help="Directory for the canonical request, response, and stream schemas")] = Path(
        "taxonomy/schemas/completion"
    ),
) -> None:
    """Export the canonical inference JSON schemas."""
    from data_plane.operations import export_schema  # noqa: PLC0415 defer runtime imports to keep CLI startup fast

    export_schema(out)
    typer.echo(f"Wrote inference schemas to {out}")
