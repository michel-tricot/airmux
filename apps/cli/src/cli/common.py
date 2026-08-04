from __future__ import annotations

import typer
from dotenv import find_dotenv, load_dotenv
from rich.console import Console

app = typer.Typer(name="airllm", no_args_is_help=True)
console = Console()


@app.callback()
def _main() -> None:
    load_dotenv(find_dotenv(usecwd=True))


SETUP = "Setup"
RESOURCES = "Resources"
TESTING = "Testing"

orgs_app = typer.Typer(help="Orgs")
keys_app = typer.Typer(help="Caller API keys")
providers_app = typer.Typer(help="Upstream providers")
models_app = typer.Typer(help="Routable models")
bundles_app = typer.Typer(help="Signed policy bundles")
test_app = typer.Typer(help="Acceptance and load testing", no_args_is_help=True)

for name, sub in (("orgs", orgs_app), ("keys", keys_app), ("providers", providers_app), ("models", models_app), ("bundles", bundles_app)):
    app.add_typer(sub, name=name, rich_help_panel=RESOURCES, no_args_is_help=True)
app.add_typer(test_app, name="test", rich_help_panel=TESTING)
