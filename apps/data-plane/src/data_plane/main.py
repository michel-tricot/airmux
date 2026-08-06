from __future__ import annotations

import os

import typer
import uvicorn

app = typer.Typer(name="airllmdp")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8080, dev: bool = False, config: str = "airllm.yml", workers: int = 1) -> None:
    os.environ["GW_CONFIG"] = config
    if dev:
        os.environ["GW_DEV"] = "1"
    # Workers share one cache dir: the SQLite outbox serializes their writes and one leaseholder flushes.
    uvicorn.run("data_plane.app:app", host=host, port=port, reload=dev, workers=None if dev else workers)
