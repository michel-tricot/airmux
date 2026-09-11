from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version

import typer
from dotenv import find_dotenv, load_dotenv
from rich.console import Console

app = typer.Typer(name="airllm", no_args_is_help=True)
console = Console()


@dataclass
class Invocation:
    """What the run as a whole was told, as opposed to any one command.

    --dev is the only such flag today. It lives here because the code that acts on it resolves a url
    deep in the client, with no command in scope to ask.
    """

    dev: bool = False
    version: bool = False


invocation = Invocation()


def _show_version(value: bool) -> bool:
    if value:
        try:
            release = version("cli")
        except PackageNotFoundError:
            release = "unknown"
        typer.echo(f"airllm {release}")
        raise typer.Exit
    return value


@app.callback()
def _main(
    dev: bool = typer.Option(False, "--dev", help="Talk to a local development stack"),
    version_: bool = typer.Option(False, "--version", callback=_show_version, is_eager=True, help="Show the CLI version and exit"),
) -> None:
    load_dotenv(find_dotenv(usecwd=True))
    invocation.dev = dev
    invocation.version = version_


SETUP = "Setup"
RESOURCES = "Resources"

orgs_app = typer.Typer(help="Organizations you belong to")
org_members_app = typer.Typer(help="People in your organization")
orgs_app.add_typer(org_members_app, name="members", no_args_is_help=True)
workspaces_app = typer.Typer(help="Isolated environments for keys, credentials and usage")
workspace_members_app = typer.Typer(help="Who can use a workspace")
workspaces_app.add_typer(workspace_members_app, name="members", no_args_is_help=True)
users_app = typer.Typer(help="Accounts across the instance")
service_accounts_app = typer.Typer(help="Machine accounts for CI and automation")
inference_keys_app = typer.Typer(help="Inference keys your apps send model requests with")
management_keys_app = typer.Typer(help="Keys for control-plane access at instance, organization, or workspace boundaries")
providers_app = typer.Typer(help="Upstream LLM providers")
provider_credentials_app = typer.Typer(help="Your own provider API keys")
models_app = typer.Typer(help="Models you can route to")
policies_app = typer.Typer(help="Workspace inference restrictions, fallbacks, and budgets")
taxonomy_app = typer.Typer(help="Apply the instance provider and model catalog")
bundles_app = typer.Typer(help="Publish configuration changes to your gateways")
events_app = typer.Typer(help="Requests, tokens and spend")
data_planes_app = typer.Typer(help="Gateways connected to this instance")
profiles_app = typer.Typer(help="Saved deployment and organization contexts")

for name, sub in (
    ("orgs", orgs_app),
    ("workspaces", workspaces_app),
    ("inference-keys", inference_keys_app),
    ("provider-credentials", provider_credentials_app),
    ("management-keys", management_keys_app),
    ("models", models_app),
    ("policies", policies_app),
    ("taxonomy", taxonomy_app),
    ("providers", providers_app),
    ("bundles", bundles_app),
    ("events", events_app),
    ("users", users_app),
    ("service-accounts", service_accounts_app),
    ("data-planes", data_planes_app),
):
    app.add_typer(sub, name=name, rich_help_panel=RESOURCES, no_args_is_help=True)
app.add_typer(profiles_app, name="profiles", rich_help_panel=SETUP, no_args_is_help=True)
