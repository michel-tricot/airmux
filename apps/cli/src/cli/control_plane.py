from __future__ import annotations

import asyncio
from pathlib import Path
from shlex import quote as shell_quote
from typing import Annotated
from urllib.parse import quote

import typer

from cli.common import control_plane_app
from cli.output import Col, FormatOption, OutputFormat
from cli.output import print_rows as _print_rows
from cli.runtime import ConfigOption, DirectoryOption, HostOption, PortOption, configuration_path, runtime_command


@control_plane_app.command()
@runtime_command
def init(
    directory: DirectoryOption = Path(),
    console_url: Annotated[str, typer.Option("--console-url", help="Public console origin")] = "http://127.0.0.1:5000",
) -> None:
    """Create connected-plane configuration and a private bootstrap key."""
    from control_plane.operations import initialize  # noqa: PLC0415 defer runtime imports to keep CLI startup fast

    initialize(directory, console_url)
    typer.echo(f"Created {directory / 'airmux.yml'} and the private data-plane bootstrap key")
    typer.echo("Set DATABASE_URL, then run:")
    typer.echo(f"  airmux control-plane migrate --config {shell_quote(str(directory / 'airmux.yml'))}")
    typer.echo(f"  airmux control-plane serve --config {shell_quote(str(directory / 'airmux.yml'))}")


@control_plane_app.command()
@runtime_command
def bootstrap_keygen(
    out: Annotated[Path, typer.Option("--out", help="New data-plane bootstrap key file")] = Path(".airmux/dataplane.key"),
) -> None:
    """Create a private bootstrap key for an existing configuration."""
    from control_plane.operations import (  # noqa: PLC0415 defer runtime imports to keep CLI startup fast
        bootstrap_keygen as generate_bootstrap_key,
    )

    generate_bootstrap_key(out)
    typer.echo(f"Wrote {out}")


@control_plane_app.command()
@runtime_command
def validate(config: ConfigOption = None) -> None:
    """Validate control-plane settings without connecting to the database."""
    from control_plane.config import load_settings  # noqa: PLC0415 defer runtime imports to keep CLI startup fast

    path = configuration_path(config, "control-plane")
    load_settings(path)
    typer.echo(f"Control-plane configuration is valid: {path}")
    typer.echo("Database connectivity is verified by migrate and serve")


@control_plane_app.command()
@runtime_command
def serve(
    config: ConfigOption = None,
    host: HostOption = "127.0.0.1",
    port: PortOption = 8000,
    dev: Annotated[bool, typer.Option("--dev", help="Apply migrations and reload Python code during development")] = False,
) -> None:
    """Run the management API in the foreground."""
    from control_plane.config import load_settings  # noqa: PLC0415 defer runtime imports to keep CLI startup fast
    from control_plane.operations import serve as serve_control_plane  # noqa: PLC0415 defer runtime imports to keep CLI startup fast

    path = configuration_path(config, "control-plane")
    load_settings(path)
    serve_control_plane(path, host=host, port=port, dev=dev)


@control_plane_app.command()
@runtime_command
def migrate(config: ConfigOption = None) -> None:
    """Apply database migrations and report the schema revision."""
    from control_plane.operations import migrate as migrate_database  # noqa: PLC0415 defer runtime imports to keep CLI startup fast

    result = migrate_database(configuration_path(config, "control-plane"))
    if result.before == result.after:
        typer.echo(f"{result.database} already at {result.after}")
    else:
        typer.echo(f"{result.database} migrated {result.before or 'empty'} -> {result.after}")


@control_plane_app.command()
@runtime_command
def owner(email: Annotated[str, typer.Option("--email", help="Existing human account to promote")], config: ConfigOption = None) -> None:
    """Recover instance access by promoting an existing account to owner."""
    from control_plane.operations import promote_owner  # noqa: PLC0415 defer runtime imports to keep CLI startup fast

    email, already = asyncio.run(promote_owner(email, configuration_path(config, "control-plane")))
    typer.echo(f"{email} is already an instance owner" if already else f"{email} is now an instance owner")


@control_plane_app.command()
@runtime_command
def taxonomy(
    file: Annotated[Path, typer.Option("--file", help="Taxonomy path, relative to the configuration file")], config: ConfigOption = None
) -> None:
    """Apply a taxonomy file and queue changed bundles for publication."""
    from control_plane.operations import apply_catalog  # noqa: PLC0415 defer runtime imports to keep CLI startup fast

    path = configuration_path(config, "control-plane")
    result = asyncio.run(apply_catalog(path, path.parent / file))
    queued = f"configuration revision {result.queued_revision}" if result.queued_revision is not None else "no configuration changes"
    typer.echo(f"Applied {file.name}: {result.providers} providers, {result.models} models; queued: {queued}")


@control_plane_app.command()
@runtime_command
def openapi(out: Annotated[str, typer.Option("--out", help="Output file; - writes YAML to stdout")] = "-") -> None:
    """Export the management API schema without configuration or a database."""
    from control_plane.operations import export_openapi  # noqa: PLC0415 defer runtime imports to keep CLI startup fast

    schema = export_openapi()
    if out == "-":
        typer.echo(schema, nl=False)
    else:
        Path(out).write_text(schema, encoding="utf-8")
        typer.echo(f"Wrote {out}")


@control_plane_app.command()
@runtime_command
def fixtures(config: ConfigOption = None, fmt: FormatOption = OutputFormat.table) -> None:
    """Seed an empty database with development accounts and print their access details."""
    from control_plane.config import load_settings  # noqa: PLC0415 defer runtime imports to keep CLI startup fast
    from control_plane.operations import seed_fixtures  # noqa: PLC0415 defer runtime imports to keep CLI startup fast

    path = configuration_path(config, "control-plane")
    result = asyncio.run(seed_fixtures(path))
    seeded = result.fixtures
    origin = load_settings(path).console_url.rstrip("/")
    access = [
        *({"kind": "login", "name": email, "value": seeded.password} for email in seeded.emails),
        {"kind": "key", "name": "inference (Acme production)", "value": seeded.inference_token},
        {"kind": "key", "name": "access (Acme)", "value": seeded.org_access_token},
        {"kind": "key", "name": "access (instance)", "value": seeded.instance_access_token},
        *(
            {"kind": "invitation", "name": email, "value": f"{origin}/invite#token={quote(token, safe='')}"}
            for email, token in seeded.invitation_tokens
        ),
    ]
    _print_rows("fixture access", access, [Col("kind", "Kind"), Col("name", "Name"), Col("value", "Value")], fmt)
    if result.models == 0:
        typer.echo("Catalog is empty; run 'airmux control-plane taxonomy --file PATH'", err=True)
    if seeded.unresolved_providers:
        typer.echo(f"Provider credentials need keys: {', '.join(seeded.unresolved_providers)}", err=True)
