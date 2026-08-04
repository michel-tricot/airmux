from __future__ import annotations

import os

import typer
import uvicorn

app = typer.Typer(name="data-plane")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8080, dev: bool = False, config: str = "airllm.yml") -> None:
    os.environ["GW_CONFIG"] = config
    if dev:
        os.environ["GW_DEV"] = "1"
    uvicorn.run("data_plane.app:app", host=host, port=port, reload=dev)
