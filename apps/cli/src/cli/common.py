from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated

import typer
from dotenv import find_dotenv, load_dotenv
from rich.console import Console

app = typer.Typer(name="airmux", help="Run an LLM gateway or manage an airmux installation", no_args_is_help=True, add_completion=False)
console = Console()


@dataclass
class Invocation:
    """What the run as a whole was told, as opposed to any one command.

    The client resolves the deployment and organization below the command handler.
    """

    dev: bool = False
    version: bool = False
    organization: str = ""


invocation = Invocation()


def _select_organization(value: str) -> str:
    invocation.organization = value
    return value


OrganizationOption = Annotated[str, typer.Option("--organization", help="Target organization ID", callback=_select_organization)]


def _show_version(value: bool) -> bool:
    if value:
        try:
            release = version("airmux")
        except PackageNotFoundError:
            release = "unknown"
        typer.echo(f"airmux {release}")
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
    invocation.organization = ""


GETTING_STARTED = "Getting started"
CONNECTION = "Connection"
SERVICES = "Services"
RESOURCES = "Manage resources"
GOODIES = "Goodies"

organizations_app = typer.Typer(help="Organizations you belong to")
org_members_app = typer.Typer(help="People in your organization")
organizations_app.add_typer(org_members_app, name="members", no_args_is_help=True)
org_invitations_app = typer.Typer(help="Email invitations to your organization")
organizations_app.add_typer(org_invitations_app, name="invitations", no_args_is_help=True)
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
policies_app = typer.Typer(help="Workspace inference restrictions and fallbacks")
catalog_app = typer.Typer(help="Apply the instance provider and model catalog")
events_app = typer.Typer(help="Requests, tokens and spend")
gateways_app = typer.Typer(help="Gateways connected to this instance")
profiles_app = typer.Typer(help="Saved deployment credentials")

gateway_app = typer.Typer(help="Initialize, validate, and run a local or connected gateway", no_args_is_help=True)
app.add_typer(gateway_app, name="gateway", rich_help_panel=SERVICES)

control_plane_app = typer.Typer(help="Initialize and run the control plane, manage its database, and recover access", no_args_is_help=True)
app.add_typer(control_plane_app, name="control-plane", rich_help_panel=SERVICES)

for name, sub in (
    ("organizations", organizations_app),
    ("workspaces", workspaces_app),
    ("inference-keys", inference_keys_app),
    ("provider-credentials", provider_credentials_app),
    ("management-keys", management_keys_app),
    ("models", models_app),
    ("policies", policies_app),
    ("catalog", catalog_app),
    ("providers", providers_app),
    ("events", events_app),
    ("users", users_app),
    ("service-accounts", service_accounts_app),
    ("gateways", gateways_app),
):
    app.add_typer(sub, name=name, rich_help_panel=RESOURCES, no_args_is_help=True)
app.add_typer(profiles_app, name="profiles", rich_help_panel=CONNECTION, no_args_is_help=True)
