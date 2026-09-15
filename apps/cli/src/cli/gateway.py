from __future__ import annotations

import json
from pathlib import Path
from shlex import quote as shell_quote
from typing import TYPE_CHECKING, Annotated

import typer

from cli.common import gateway_app
from cli.runtime import ConfigOption, DirectoryOption, HostOption, PortOption, configuration_path, runtime_command

if TYPE_CHECKING:
    from data_plane.setup import GatewayGuide


def next_steps(guide: GatewayGuide, config: Path, inference_key: Path) -> tuple[str, ...]:
    providers = tuple(provider for provider in guide.providers if provider.models)
    provider = next((candidate for candidate in providers if candidate.configured_variable), providers[0])
    model_id = provider.models[0]
    model = json.dumps(model_id, ensure_ascii=False)
    body = json.dumps(
        {
            "model": model_id,
            "messages": [{"role": "user", "content": "Say hello in one word."}],
            "max_completion_tokens": 16,
        },
        separators=(",", ":"),
    )
    provider_step = (
        (f"  1. Provider key: {provider.configured_variable} is set for {model}",)
        if provider.configured_variable
        else (f"  1. Set the provider key used by {model}:", f"     export {provider.suggested_variable}='your-provider-key'")
    )
    return (
        "Next:",
        *provider_step,
        "  2. Start the gateway:",
        f"     tokkeeper gateway serve --config {shell_quote(str(config))}",
        "  3. In another terminal, verify inference:",
        f'     export TOKKEEPER_INFERENCE_KEY="$(cat {shell_quote(str(inference_key))})"',
        "     curl --fail http://127.0.0.1:8080/readyz",
        "     curl --fail-with-body http://127.0.0.1:8080/inf/v1/chat/completions \\",
        '       -H "Authorization: Bearer $TOKKEEPER_INFERENCE_KEY" \\',
        "       -H 'Content-Type: application/json' \\",
        f"       -d {shell_quote(body)}",
    )


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
    if taxonomy is None:
        typer.echo(f"Created {config}, {directory / 'taxonomy.yml'}, and {inference_key}")
    else:
        typer.echo(f"Created {config} and {inference_key}")
    for line in next_steps(guide, config, inference_key):
        typer.echo(line)


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
