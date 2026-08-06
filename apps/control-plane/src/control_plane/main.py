from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import typer
import uvicorn
from dotenv import dotenv_values, load_dotenv, set_key
from rich.console import Console

from control_plane.compiler import compile_and_store
from control_plane.config import load_settings
from control_plane.db import standalone_engine, standalone_transaction, transaction
from control_plane.migrate import run_migrations
from control_plane.models import Org
from control_plane.setup import (
    DEFAULT_CONFIG_YML,
    AdminToken,
    NotAnAdminError,
    create_admin,
    ensure_admin,
    ensure_bundle,
    ensure_org,
    ensure_signing_keys,
)
from control_plane.taxonomy import apply_taxonomy, parse_taxonomy

if TYPE_CHECKING:
    from collections.abc import Iterator

app = typer.Typer(name="control-plane", no_args_is_help=True)

admin_app = typer.Typer(help="Instance admins", no_args_is_help=True)
app.add_typer(admin_app, name="admin")

console = Console()


@contextlib.contextmanager
def _step(label: str) -> Iterator[dict[str, str]]:
    """One init step: spinner while the body runs, then a checkmark line with the message the body set."""
    state = {"message": ""}
    try:
        with console.status(f"[bold]{label}[/bold]"):
            yield state
    except Exception:
        console.print(f"[red]✗[/red] [dim]{label:>8}[/dim]  {state['message'] or 'failed'}")
        raise
    console.print(f"[green]✓[/green] [dim]{label:>8}[/dim]  {state['message']}")


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
    run_migrations()


@app.command()
def init(  # noqa: PLR0913, PLR0915, PLR0917 the flags and sequential steps are the command's interface
    email: str = typer.Option(..., "--email", prompt="Admin email", help="Instance admin to create"),
    name: str = typer.Option("", help="Admin display name, defaults to the email"),
    org: str = typer.Option("org-dev", help="Initial org id, also written into the data plane config"),
    config: str = typer.Option("airllm.yml", help="Shared config for both planes, written if missing"),
    env_file: str = typer.Option(".env", help="Where the signing keys and minted tokens land"),
    cache_dir: str = typer.Option(".airllm", help="Data plane bundle cache, written into the config"),
    taxonomy_file: str = typer.Option("taxonomy.yml", "--taxonomy", help="Models taxonomy path, resolved next to the config"),
    control_plane_url: str = typer.Option("http://127.0.0.1:8000", help="Control plane URL written into the data plane config"),
    db_url: str = typer.Option("sqlite+aiosqlite:///airllm.db", help="Database URL written into the config"),
    skip_key: bool = typer.Option(False, help="Do not mint the wildcard caller key (AIRLLM_TOKEN)"),
) -> None:
    """Set up a ready-to-serve control plane: keys, config, taxonomy, schema, admin, org, tokens, and bundle v1.

    Idempotent: every step keeps what already exists, so re-running converges and never churns
    tokens. After init the only missing pieces are the provider API keys.
    """
    env_path = Path(env_file)
    config_path = Path(config)
    with _step("secrets") as s:
        generated, reused = ensure_signing_keys(env_path)
        parts = (f"generated {', '.join(generated)}" if generated else None, f"reused {', '.join(reused)}" if reused else None)
        s["message"] = f"{', '.join(p for p in parts if p)}, saved with their public keys to [bold]{env_path.resolve()}[/bold]"
    with _step("config") as s:
        if config_path.exists():
            s["message"] = f"kept existing [bold]{config_path}[/bold]"
        else:
            content = DEFAULT_CONFIG_YML.format(db_url=db_url, control_plane_url=control_plane_url, org=org, cache_dir=cache_dir)
            config_path.write_text(content, encoding="utf-8")
            s["message"] = f"wrote [bold]{config_path}[/bold] for both planes, control plane at {control_plane_url}"
    os.environ["GW_CONFIG"] = config
    load_dotenv(env_path, override=True)
    settings = load_settings(config_path)
    taxonomy_path = config_path.parent / taxonomy_file
    with _step("taxonomy") as s:
        if not taxonomy_path.exists():
            s["message"] = f"[bold]{taxonomy_path}[/bold] not found; provide a models taxonomy (see taxonomy.yml in the repo)"
            raise typer.Exit(1)
        s["message"] = f"using [bold]{taxonomy_path}[/bold]"
    with _step("database") as s:
        run_migrations()
        s["message"] = "migrated to the latest schema"

    async def db_phase() -> None:
        stored = dotenv_values(env_path)
        async with standalone_engine(settings.database.url) as factory:
            with _step("admin") as s:
                async with transaction(factory):
                    s["message"], minted = await ensure_admin(settings, email, name, stored)
                for env_name, token in minted.items():
                    set_key(env_path, env_name, token)
            with _step("org") as s:
                async with transaction(factory):
                    s["message"], minted = await ensure_org(settings, org, stored, skip_key=skip_key)
                for env_name, token in minted.items():
                    set_key(env_path, env_name, token)
            with _step("models") as s:
                spec = parse_taxonomy(taxonomy_path)
                async with transaction(factory):
                    providers, models = await apply_taxonomy(spec, org)
                s["message"] = f"applied {providers} providers, {models} models from {taxonomy_path.name}"
            with _step("bundle") as s:
                async with transaction(factory):
                    s["message"] = await ensure_bundle(settings, org)

    try:
        asyncio.run(db_phase())
    except NotAnAdminError:
        console.print(f"[red]{email} belongs to an existing user that is not an instance admin[/red]")
        raise typer.Exit(1) from None
    console.print()
    console.print("ready, start the planes with:")
    console.print("  [bold]uv run control-plane serve --dev[/bold]")
    console.print("  [bold]uv run data-plane --dev[/bold]")
    console.print(f"[dim]tokens are in {env_path.resolve()}; add provider keys (OPENAI_API_KEY, ANTHROPIC_API_KEY) there to route models[/dim]")


@app.command()
def taxonomy(
    config: str = "airllm.yml",
    file: str = typer.Option("taxonomy.yml", "--file", help="Models taxonomy path, resolved next to the config"),
    org: str = typer.Option("", help="Org to apply the taxonomy to; defaults to the sole org"),
) -> None:
    """Apply the models taxonomy to the catalog and compile a new bundle; run after editing the taxonomy file."""
    settings = load_settings(config)
    taxonomy_path = Path(config).parent / file
    if not taxonomy_path.exists():
        typer.echo(f"{taxonomy_path} does not exist", err=True)
        raise typer.Exit(1)
    spec = parse_taxonomy(taxonomy_path)

    async def run() -> tuple[str, int, int, int]:
        async with standalone_transaction(settings.database.url):
            orgs = await Org.find()
            target = org or (orgs[0].id if len(orgs) == 1 else "")
            if not target:
                hint = "no org exists yet, run `control-plane init` first" if not orgs else "multiple orgs exist, pass --org"
                typer.echo(hint, err=True)
                raise typer.Exit(1)
            providers, models = await apply_taxonomy(spec, target)
            version = await compile_and_store(target, uuid4(), datetime.now(tz=UTC), settings.bundle.staleness_bound, settings.bundle.signing_key)
            return target, providers, models, version

    target, providers, models, version = asyncio.run(run())
    typer.echo(f"applied {taxonomy_path.name} to {target}: {providers} providers, {models} models; compiled bundle v{version}")


@admin_app.command()
def create(email: str, name: str = "", config: str = "airllm.yml", env_file: str = ".env", if_missing: bool = False) -> None:
    """Create an instance admin and mint their instance token, saved to .env as GW_ADMIN_MGMT_TOKEN.

    An existing admin gets a fresh token, the break-glass path for lost credentials; --if-missing
    makes that case a no-op so scripted setups never churn tokens.
    """
    settings = load_settings(config)

    async def run() -> AdminToken | None:
        async with standalone_transaction(settings.database.url):
            return await create_admin(settings, email, name, if_missing=if_missing)

    try:
        minted = asyncio.run(run())
    except NotAnAdminError:
        typer.echo(f"{email} belongs to an existing user that is not an instance admin, refusing to mint", err=True)
        raise typer.Exit(1) from None
    if minted is None:
        typer.echo(f"instance admin {email} already exists, nothing to do")
        return
    set_key(env_file, "GW_ADMIN_MGMT_TOKEN", minted.token)
    verb = "created instance admin" if minted.created else "existing instance admin"
    typer.echo(f"{verb} {minted.user_id} ({email}), minted instance token {minted.token_id}, saved to {env_file} as GW_ADMIN_MGMT_TOKEN")
    typer.echo(minted.token)
