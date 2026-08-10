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
org_members_app = typer.Typer(help="Org members, the users a management key's org is made of")
orgs_app.add_typer(org_members_app, name="members", no_args_is_help=True)
workspaces_app = typer.Typer(help="Workspaces, the org scopes inference keys live in")
workspace_members_app = typer.Typer(help="Workspace members, drawn from the org")
workspaces_app.add_typer(workspace_members_app, name="members", no_args_is_help=True)
users_app = typer.Typer(help="Users and org memberships")
service_accounts_app = typer.Typer(help="Service accounts, machine principals with derived emails")
inference_keys_app = typer.Typer(help="Inference API keys, the caller credentials the gateway verifies")
management_keys_app = typer.Typer(help="Management API keys, user-bound credentials for one org")
instance_keys_app = typer.Typer(help="Instance API keys, admin credentials for the instance endpoints")
providers_app = typer.Typer(help="Upstream providers")
provider_credentials_app = typer.Typer(help="Provider API keys this org brings; values go to the secret store, never to the database")
models_app = typer.Typer(help="Routable models")
bundles_app = typer.Typer(help="Signed policy bundles")
events_app = typer.Typer(help="Usage events ingested from data planes")
data_planes_app = typer.Typer(help="Data planes registered with the instance through their heartbeats")
test_app = typer.Typer(help="Acceptance and load testing", no_args_is_help=True)

for name, sub in (
    ("orgs", orgs_app),
    ("workspaces", workspaces_app),
    ("users", users_app),
    ("service-accounts", service_accounts_app),
    ("inference-keys", inference_keys_app),
    ("management-keys", management_keys_app),
    ("instance-keys", instance_keys_app),
    ("providers", providers_app),
    ("provider-credentials", provider_credentials_app),
    ("models", models_app),
    ("bundles", bundles_app),
    ("events", events_app),
    ("data-planes", data_planes_app),
):
    app.add_typer(sub, name=name, rich_help_panel=RESOURCES, no_args_is_help=True)
app.add_typer(test_app, name="test", rich_help_panel=TESTING)
