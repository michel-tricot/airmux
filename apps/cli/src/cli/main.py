from __future__ import annotations

import typer

app = typer.Typer(name="airllm", no_args_is_help=True)


@app.command()
def seed() -> None:
    raise NotImplementedError


@app.command("compile")
def compile_bundle() -> None:
    raise NotImplementedError


@app.command()
def verify() -> None:
    raise NotImplementedError


@app.command()
def loadgen() -> None:
    raise NotImplementedError
