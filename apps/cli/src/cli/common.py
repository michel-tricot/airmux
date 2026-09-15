from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version

import typer
from dotenv import find_dotenv, load_dotenv
from rich.console import Console

app = typer.Typer(name="tokkeeper", help="Run an LLM gateway or manage a TokKeeper installation", no_args_is_help=True, add_completion=False)
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
            release = version("tokkeeper")
        except PackageNotFoundError:
            release = "unknown"
        typer.echo(f"tokkeeper {release}")
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


GETTING_STARTED = "Getting started"
CONNECTION = "Connection"
SERVICES = "Services"
RESOURCES = "Manage resources"
GOODIES = "Goodies"

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
rules_app = typer.Typer(help="Reusable workspace inference rules")
policies_app = typer.Typer(help="Workspace inference restrictions, fallbacks, and budgets")
catalog_app = typer.Typer(help="Apply the instance provider and model catalog")
bundles_app = typer.Typer(help="Publish configuration changes to your gateways")
events_app = typer.Typer(help="Requests, tokens and spend")
gateways_app = typer.Typer(help="Gateways connected to this instance")
profiles_app = typer.Typer(help="Saved deployment and organization contexts")

gateway_app = typer.Typer(help="Initialize, validate, and run a local or connected gateway", no_args_is_help=True)
app.add_typer(gateway_app, name="gateway", rich_help_panel=SERVICES)

control_plane_app = typer.Typer(help="Initialize and run the control plane, manage its database, and recover access", no_args_is_help=True)
app.add_typer(control_plane_app, name="control-plane", rich_help_panel=SERVICES)

for name, sub in (
    ("orgs", orgs_app),
    ("workspaces", workspaces_app),
    ("inference-keys", inference_keys_app),
    ("provider-credentials", provider_credentials_app),
    ("management-keys", management_keys_app),
    ("models", models_app),
    ("rules", rules_app),
    ("policies", policies_app),
    ("catalog", catalog_app),
    ("providers", providers_app),
    ("bundles", bundles_app),
    ("events", events_app),
    ("users", users_app),
    ("service-accounts", service_accounts_app),
    ("gateways", gateways_app),
):
    app.add_typer(sub, name=name, rich_help_panel=RESOURCES, no_args_is_help=True)
app.add_typer(profiles_app, name="profiles", rich_help_panel=CONNECTION, no_args_is_help=True)
