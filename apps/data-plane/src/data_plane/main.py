from __future__ import annotations

import typer
import uvicorn

app = typer.Typer(name="data-plane")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8080, reload: bool = False) -> None:
    uvicorn.run("data_plane.app:app", host=host, port=port, reload=reload)
