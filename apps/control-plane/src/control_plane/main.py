from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

import typer
import uvicorn
import yaml
from rich import box
from rich.console import Console
from rich.table import Table
from sqlalchemy.engine import make_url

from contract.secrets.file import write_private_text
from contract.taxonomy import parse_taxonomy
from control_plane.app import create_app
from control_plane.authz import InstanceRole
from control_plane.compiler import publish_changes
from control_plane.config import Settings, database_url, load_settings
from control_plane.db import standalone_transaction
from control_plane.fixtures import Fixtures, apply_fixtures
from control_plane.keys import new_management_key
from control_plane.migrate import current_revision, head_revision, run_migrations
from control_plane.models import Model, Org, User, set_actor
from control_plane.taxonomy import apply_taxonomy

if TYPE_CHECKING:
    from collections.abc import Sequence

app = typer.Typer(name="tokkeeper-control-plane", no_args_is_help=True)

console = Console()


def _table(title: str, headers: tuple[str, ...], rows: Sequence[tuple[str, ...]]) -> Table:
    """The tokkeeper CLI renders resource listings through cli.output; this is the same look for the one
    control-plane command with rows to show, which cannot import across apps."""
    table = Table(title=title, box=box.ROUNDED, header_style="bold", title_justify="left")
    for header in headers:
        table.add_column(header)
    for row in rows:
        table.add_row(*row)
    return table


def _database_url(config: str) -> str:
    """Load the database alone for commands that do not need full application settings."""
    os.environ["TOKKEEPER_CONFIG"] = config
    return database_url()


@app.command()
def bootstrap_keygen(out: str = typer.Option(".tokkeeper/dataplane.key", "--out", help="Data-plane bootstrap key file")) -> None:
    """Generate the shared pool key used to bootstrap control and data planes."""
    key_path = Path(out)
    if key_path.exists():
        typer.echo(f"{key_path} exists", err=True)
        raise typer.Exit(1)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    token, _ = new_management_key()
    write_private_text(key_path, token)
    typer.echo(f"wrote {key_path}")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, dev: bool = False, config: str = "tokkeeper.yml") -> None:
    os.environ["TOKKEEPER_CONFIG"] = config
    if dev:
        run_migrations()
    uvicorn.run("control_plane.app:create_app", factory=True, host=host, port=port, reload=dev)


@app.command()
def owner(
    email: str = typer.Option(..., "--email", help="Existing account to promote"),
    config: str = "tokkeeper.yml",
) -> None:
    """Grant instance authority to a human account that has already signed up."""
    submitted_email = email
    try:
        email = User.normalize_email(email)
    except ValueError as e:
        typer.echo(f"{submitted_email}: {e}", err=True)
        raise typer.Exit(1) from e
    settings_url = _database_url(config)

    async def run() -> tuple[str, bool]:
        async with standalone_transaction(settings_url):
            user = await User.first(User.email == email)
            if user is None:
                msg = "account does not exist; ask its owner to sign up first"
                raise ValueError(msg)
            if user.service_account:
                msg = "instance authority belongs to a human account"
                raise ValueError(msg)
            if user.instance_role == InstanceRole.owner:
                return email, True
            await set_actor(user.id)
            await User.change_instance_role(user.id, InstanceRole.owner)
            return email, False

    try:
        granted, already = asyncio.run(run())
    except ValueError as e:
        typer.echo(f"{email}: {e}", err=True)
        raise typer.Exit(1) from e
    typer.echo(f"{granted} is already an instance owner" if already else f"{granted} is now an instance owner")


@app.command()
def fixtures(config: str = "tokkeeper.yml") -> None:
    """Seed a fresh instance with development data: orgs, workspaces, keys, and recorded usage for frontend work.

    Seeds an empty database only, and refuses one that already holds accounts. There is no merge
    and no partial reset: to start over, drop the database and recreate it. Ids and secrets are
    derived from names rather than minted, so console URLs, the shared login, and the tokens below
    come back identical every time you do.
    """
    settings = load_settings(config)

    async def run() -> tuple[Fixtures, list[tuple[str, int]], int]:
        async with settings.secrets.build() as secret_store, standalone_transaction(settings.database.url):
            seeded = await apply_fixtures(datetime.now(tz=UTC), secret_store)
            now = datetime.now(tz=UTC)
            orgs = {org.id: org.name for org in await Org.find()}
            versions = [(orgs[bundle.org_id], bundle.version) for bundle in await publish_changes(now)]
            return seeded, versions, len(await Model.find())

    try:
        seeded, versions, models = asyncio.run(run())
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e

    typer.echo(f"seeded; bundles: {', '.join(f'{name} v{version}' for name, version in versions)}")
    if models == 0:
        typer.echo("catalog is empty, so the bundles route nothing; run `tokkeeper-control-plane taxonomy` to fill it")
    if seeded.unresolved_providers:
        names = ", ".join(seeded.unresolved_providers)
        typer.echo(f"no key behind the seeded {names} credentials; supply one with `tokkeeper provider-credentials add <provider>`")

    logins = [(email, seeded.password, "instance owner" if email == seeded.admin_email else "member") for email in seeded.emails]
    keys = [
        ("inference (Acme production)", seeded.inference_token),
        ("access (Acme)", seeded.org_access_token),
        ("access (instance)", seeded.instance_access_token),
    ]
    invitations = [(email, f"{settings.console_url.rstrip('/')}/invite#token={quote(token, safe='')}") for email, token in seeded.invitation_tokens]
    console.print(_table("logins", ("Email", "Password", "Role"), logins))
    console.print(_table("keys", ("Key", "Token"), keys))
    console.print(_table("invitations", ("Email", "Share link"), invitations))


@app.command()
def openapi(out: str = typer.Option("-", "--out", help="Write the spec here; - writes it to stdout")) -> None:
    """Export the API spec as YAML; it is committed at lib/api-spec/openapi.yaml and the console and CLI clients generate from it.

    The spec depends on the routes alone, so this touches no database and no config file.
    """
    settings = Settings()
    spec = yaml.safe_dump(create_app(settings).openapi(), sort_keys=False, allow_unicode=True, width=120)
    if out == "-":
        typer.echo(spec, nl=False)
    else:
        Path(out).write_text(spec, encoding="utf-8")
        typer.echo(f"wrote {out}")


@app.command()
def migrate(config: str = "tokkeeper.yml") -> None:
    url = _database_url(config)
    shown = make_url(url).render_as_string(hide_password=True)
    before = current_revision(url)
    run_migrations()
    head = head_revision()
    if before == head:
        typer.echo(f"{shown} already at {head}")
    else:
        typer.echo(f"{shown} migrated {before or 'empty'} -> {head}")


@app.command()
def taxonomy(
    config: str = "tokkeeper.yml",
    file: str = typer.Option("taxonomy.yml", "--file", help="Models taxonomy path, resolved next to the config"),
) -> None:
    """Apply the models taxonomy to the instance catalog and publish changed organization configurations."""
    settings = load_settings(config)
    taxonomy_path = Path(config).parent / file
    if not taxonomy_path.exists():
        typer.echo(f"{taxonomy_path} does not exist", err=True)
        raise typer.Exit(1)
    spec = parse_taxonomy(taxonomy_path)

    async def run() -> tuple[int, int, list[tuple[str, int]]]:
        async with standalone_transaction(settings.database.url):
            await set_actor("root")
            providers, models = await apply_taxonomy(spec)
            now = datetime.now(tz=UTC)
            orgs = {org.id: org.name for org in await Org.find()}
            versions = [(orgs[bundle.org_id], bundle.version) for bundle in await publish_changes(now)]
            return providers, models, versions

    providers, models, versions = asyncio.run(run())
    bundles_part = ", ".join(f"{org_id} v{version}" for org_id, version in versions) or "no bundle changes"
    typer.echo(f"applied {taxonomy_path.name}: {providers} providers, {models} models; published: {bundles_part}")
