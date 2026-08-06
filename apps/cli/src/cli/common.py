from __future__ import annotations

import typer
from dotenv import find_dotenv, load_dotenv
from rich.console import Console

app = typer.Typer(name="airllm", no_args_is_help=True)
console = Console()


@app.callback()
def _main() -> None:
    load_dotenv(find_dotenv(usecwd=True))


RESOURCES = "Resources"
TESTING = "Testing"

orgs_app = typer.Typer(help="Orgs")
users_app = typer.Typer(help="Users and org memberships")
service_accounts_app = typer.Typer(help="Service accounts, machine principals with derived emails")
keys_app = typer.Typer(help="Inference API keys")
tokens_app = typer.Typer(help="Management API tokens")
providers_app = typer.Typer(help="Upstream providers")
models_app = typer.Typer(help="Routable models")
bundles_app = typer.Typer(help="Signed policy bundles")
events_app = typer.Typer(help="Usage events ingested from data planes")
instances_app = typer.Typer(help="Registered data plane instances")
test_app = typer.Typer(help="Acceptance and load testing", no_args_is_help=True)

for name, sub in (
    ("orgs", orgs_app),
    ("users", users_app),
    ("service-accounts", service_accounts_app),
    ("keys", keys_app),
    ("tokens", tokens_app),
    ("providers", providers_app),
    ("models", models_app),
    ("bundles", bundles_app),
    ("events", events_app),
    ("instances", instances_app),
):
    app.add_typer(sub, name=name, rich_help_panel=RESOURCES, no_args_is_help=True)
app.add_typer(test_app, name="test", rich_help_panel=TESTING)
