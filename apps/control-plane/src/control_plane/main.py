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
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from rich import box
from rich.console import Console
from rich.table import Table
from sqlalchemy.engine import make_url

from contract import private_key_to_b64, public_key_to_b64
from contract.secrets.file import write_private_text
from control_plane.app import create_app
from control_plane.authz import InstanceRole
from control_plane.compiler import publish_changes
from control_plane.config import BundlePolicy, Settings, database_url, load_settings
from control_plane.db import standalone_transaction
from control_plane.fixtures import Fixtures, apply_fixtures
from control_plane.migrate import current_revision, head_revision, run_migrations
from control_plane.models import Model, Org, User, set_actor
from control_plane.taxonomy import apply_taxonomy, parse_taxonomy

if TYPE_CHECKING:
    from collections.abc import Sequence

app = typer.Typer(name="airllmcp", no_args_is_help=True)

console = Console()


def _table(title: str, headers: tuple[str, ...], rows: Sequence[tuple[str, ...]]) -> Table:
    """The airllm CLI renders resource listings through cli.output; this is the same look for the one
    control-plane command with rows to show, which cannot import across apps."""
    table = Table(title=title, box=box.ROUNDED, header_style="bold", title_justify="left")
    for header in headers:
        table.add_column(header)
    for row in rows:
        table.add_row(*row)
    return table


def _database_url(config: str) -> str:
    """The database alone, for the commands that touch rows without needing a signing key."""
    os.environ["GW_CONFIG"] = config
    return database_url()


@app.command()
def keygen(
    out: str = typer.Option(".airllm/signing.key", "--out", help="Bundle private key file; the public key is written to <out>.pub"),
    force: bool = typer.Option(False, "--force", help="Rotate an existing key; this invalidates every bundle signed with the old one"),
) -> None:
    """Generate the bundle signing key pair, the one secret the instance cannot mint for itself.

    Refuses to overwrite an existing key file unless --force is given. Point the config at the files
    with file: refs: control_plane.bundle.signing_key and data_plane.bundle.public_key.
    """
    key_path = Path(out)
    public_path = key_path.with_suffix(".pub")
    if key_path.exists() and not force:
        typer.echo(f"{key_path} exists; pass --force to rotate (invalidates existing bundles)", err=True)
        raise typer.Exit(1)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    write_private_text(key_path, private_key_to_b64(key))
    write_private_text(public_path, public_key_to_b64(key.public_key()))
    typer.echo(f"wrote {key_path} and {public_path}")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, dev: bool = False, config: str = "airllm.yml") -> None:
    os.environ["GW_CONFIG"] = config
    if dev:
        run_migrations()
    uvicorn.run("control_plane.app:create_app", factory=True, host=host, port=port, reload=dev)


@app.command()
def owner(
    email: str = typer.Option(..., "--email", help="Existing account to promote"),
    config: str = "airllm.yml",
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
            user.instance_role = InstanceRole.owner
            await user.save()
            return email, False

    try:
        granted, already = asyncio.run(run())
    except ValueError as e:
        typer.echo(f"{email}: {e}", err=True)
        raise typer.Exit(1) from e
    typer.echo(f"{granted} is already an instance owner" if already else f"{granted} is now an instance owner")


@app.command()
def fixtures(config: str = "airllm.yml") -> None:
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
            versions = [(orgs[bundle.org_id], bundle.version) for bundle in await publish_changes(now, settings.bundle.signing_key)]
            return seeded, versions, len(await Model.find())

    try:
        seeded, versions, models = asyncio.run(run())
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e

    typer.echo(f"seeded; bundles: {', '.join(f'{name} v{version}' for name, version in versions)}")
    if models == 0:
        typer.echo("catalog is empty, so the bundles route nothing; run `airllmcp taxonomy` to fill it")
    if seeded.unresolved_providers:
        names = ", ".join(seeded.unresolved_providers)
        typer.echo(f"no key behind the seeded {names} credentials; supply one with `airllm provider-credentials add <provider>`")

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

    The spec depends on the routes alone, so this runs against an ephemeral signing key and touches no database and no config file.
    """
    settings = Settings(bundle=BundlePolicy(signing_key=private_key_to_b64(Ed25519PrivateKey.generate())))
    spec = yaml.safe_dump(create_app(settings).openapi(), sort_keys=False, allow_unicode=True, width=120)
    if out == "-":
        typer.echo(spec, nl=False)
    else:
        Path(out).write_text(spec, encoding="utf-8")
        typer.echo(f"wrote {out}")


@app.command()
def migrate(config: str = "airllm.yml") -> None:
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
    config: str = "airllm.yml",
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
            versions = [(orgs[bundle.org_id], bundle.version) for bundle in await publish_changes(now, settings.bundle.signing_key)]
            return providers, models, versions

    providers, models, versions = asyncio.run(run())
    bundles_part = ", ".join(f"{org_id} v{version}" for org_id, version in versions) or "no bundle changes"
    typer.echo(f"applied {taxonomy_path.name}: {providers} providers, {models} models; published: {bundles_part}")
