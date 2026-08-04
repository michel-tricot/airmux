from __future__ import annotations

import typer
import uvicorn

app = typer.Typer(name="control-plane")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    uvicorn.run("control_plane.app:app", host=host, port=port, reload=reload)
