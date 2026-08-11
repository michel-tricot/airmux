from __future__ import annotations

from dataclasses import dataclass

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


invocation = Invocation()


@app.callback()
def _main(dev: bool = typer.Option(False, "--dev", help="Talk to a local development stack")) -> None:
    load_dotenv(find_dotenv(usecwd=True))
    invocation.dev = dev


SETUP = "Setup"
ORG = "Your organization"
ADMIN = "Instance admin"
TESTING = "Testing"
"""The two audiences the commands split across, and the credential each carries.

Everything under ORG works with the key `airllm login` stores. Everything under ADMIN needs an
instance key, which is a different credential with instance-wide reach; the console mints the first
one. A few groups serve both, and their admin commands carry ADMIN individually.
"""

orgs_app = typer.Typer(help="Organizations you belong to")
org_members_app = typer.Typer(help="People in your organization")
orgs_app.add_typer(org_members_app, name="members", no_args_is_help=True)
workspaces_app = typer.Typer(help="Isolated environments for keys, credentials and usage")
workspace_members_app = typer.Typer(help="Who can use a workspace")
workspaces_app.add_typer(workspace_members_app, name="members", no_args_is_help=True)
users_app = typer.Typer(help="Accounts across the instance")
service_accounts_app = typer.Typer(help="Machine accounts for CI and automation")
inference_keys_app = typer.Typer(help="API keys your apps send requests with")
management_keys_app = typer.Typer(help="API keys for automating this CLI")
instance_keys_app = typer.Typer(help="Admin keys for instance-wide operations")
providers_app = typer.Typer(help="Upstream LLM providers")
provider_credentials_app = typer.Typer(help="Your own provider API keys")
models_app = typer.Typer(help="Models you can route to")
bundles_app = typer.Typer(help="Publish configuration changes to your gateways")
events_app = typer.Typer(help="Requests, tokens and spend")
data_planes_app = typer.Typer(help="Gateways connected to this instance")
test_app = typer.Typer(help="Send test traffic through a gateway", no_args_is_help=True)

for name, sub, panel in (
    ("orgs", orgs_app, ORG),
    ("workspaces", workspaces_app, ORG),
    ("inference-keys", inference_keys_app, ORG),
    ("provider-credentials", provider_credentials_app, ORG),
    ("management-keys", management_keys_app, ORG),
    ("models", models_app, ORG),
    ("providers", providers_app, ORG),
    ("bundles", bundles_app, ORG),
    ("events", events_app, ORG),
    ("users", users_app, ADMIN),
    ("service-accounts", service_accounts_app, ADMIN),
    ("instance-keys", instance_keys_app, ADMIN),
    ("data-planes", data_planes_app, ADMIN),
):
    app.add_typer(sub, name=name, rich_help_panel=panel, no_args_is_help=True)
app.add_typer(test_app, name="test", rich_help_panel=TESTING)
