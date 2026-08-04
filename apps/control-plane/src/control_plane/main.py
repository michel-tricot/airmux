from __future__ import annotations

import os

import typer
import uvicorn

app = typer.Typer(name="control-plane")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, dev: bool = False) -> None:
    if dev:
        os.environ["GW_DEV"] = "1"
    uvicorn.run("control_plane.app:app", host=host, port=port, reload=dev)
