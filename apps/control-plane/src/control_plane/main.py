from __future__ import annotations

import os

import typer
import uvicorn

from control_plane.migrate import run_migrations

app = typer.Typer(name="control-plane", no_args_is_help=True)


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
def mint_root_token(config: str = "airllm.yml", env_file: str = ".env") -> None:
    """Mint an instance-scoped management token and save it to .env as GW_MGMT_TOKEN."""
    from datetime import UTC, datetime  # noqa: PLC0415 lazy import keeps CLI startup fast
    from uuid import uuid4  # noqa: PLC0415 lazy import keeps CLI startup fast

    from dotenv import set_key  # noqa: PLC0415 lazy import keeps CLI startup fast

    from contract import private_key_from_b64  # noqa: PLC0415 lazy import keeps CLI startup fast
    from control_plane.config import load_settings  # noqa: PLC0415 lazy import keeps CLI startup fast
    from control_plane.tokens import mint_management_token  # noqa: PLC0415 lazy import keeps CLI startup fast

    os.environ["GW_CONFIG"] = config
    settings = load_settings()
    token_id = f"mt-{uuid4().hex[:8]}"
    token = mint_management_token(None, private_key_from_b64(settings.auth.token_signing_key), datetime.now(tz=UTC), token_id)
    set_key(env_file, "GW_MGMT_TOKEN", token)
    typer.echo(f"minted instance management token {token_id}, saved to {env_file} as GW_MGMT_TOKEN")
    typer.echo(token)
