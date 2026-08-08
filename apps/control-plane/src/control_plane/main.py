from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path

import typer
import uvicorn
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.engine import make_url

from contract import private_key_to_b64, public_key_to_b64, uuid7
from control_plane.compiler import compile_and_store
from control_plane.config import database_url, load_settings
from control_plane.db import standalone_transaction
from control_plane.migrate import current_revision, head_revision, run_migrations
from control_plane.models import Org, set_actor
from control_plane.taxonomy import apply_taxonomy, parse_taxonomy

app = typer.Typer(name="airllmcp", no_args_is_help=True)


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
    key_path.write_text(private_key_to_b64(key), encoding="utf-8")
    key_path.chmod(0o600)
    public_path.write_text(public_key_to_b64(key.public_key()), encoding="utf-8")
    typer.echo(f"wrote {key_path} and {public_path}")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, dev: bool = False, config: str = "airllm.yml") -> None:
    os.environ["GW_CONFIG"] = config
    if dev:
        os.environ["GW_DEV"] = "1"
        run_migrations()
    uvicorn.run("control_plane.app:create_app", factory=True, host=host, port=port, reload=dev)


@app.command()
def migrate(config: str = "airllm.yml") -> None:
    os.environ["GW_CONFIG"] = config
    url = database_url()
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
    """Apply the models taxonomy to the instance catalog and compile a new bundle per org; run after editing the taxonomy file."""
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
            versions = [
                (org.name, (await compile_and_store(org.id, uuid7(), now, settings.bundle.staleness_bound, settings.bundle.signing_key)).version)
                for org in await Org.find()
            ]
            return providers, models, versions

    providers, models, versions = asyncio.run(run())
    bundles_part = ", ".join(f"{org_id} v{version}" for org_id, version in versions) or "no orgs yet"
    typer.echo(f"applied {taxonomy_path.name}: {providers} providers, {models} models; compiled bundles: {bundles_part}")
