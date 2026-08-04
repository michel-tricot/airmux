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
    uvicorn.run("control_plane.app:app", host=host, port=port, reload=dev)


@app.command()
def migrate(config: str = "airllm.yml") -> None:
    os.environ["GW_CONFIG"] = config
    run_migrations()
