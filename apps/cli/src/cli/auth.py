from __future__ import annotations

import os
import socket
import sys
import time
import webbrowser
from typing import TYPE_CHECKING, NamedTuple

import typer
from rich.panel import Panel

if TYPE_CHECKING:
    import httpx

from cli.client import api_error, ensure_ok, payload, resolve_control_plane_url
from cli.common import SETUP, app, console, orgs_app
from cli.output import Col, FormatOption, OutputFormat, print_rows
from cli.profiles import DEFAULT_CONSOLE_URL, active_profile, config_path, load_config, set_active, upsert_profile

MINE_COLS = [
    Col("id", "ID", style="dim", no_wrap=True),
    Col("name", "Name", max_width=40),
    Col("kind", "Kind"),
]


HTTP_GONE = 410

CSRF = {"X-Requested-With": "airllm-cli"}
DATA_PLANE_PERMISSIONS = ["bundles.read", "usage.ingest", "data-planes.heartbeat"]


def _client_name() -> str:
    return f"cli@{socket.gethostname()}"


def _existing_access_key(control_plane_url: str) -> str | None:
    profile = active_profile()
    if profile is None or str(profile.get("control_plane_url", "")).rstrip("/") != control_plane_url.rstrip("/"):
        return None
    token = profile.get("token")
    return str(token) if token else None


def _payload_or_die(resp: httpx.Response, what: str) -> dict:
    if not resp.is_success:
        console.print(f"[red]{what} failed ({resp.status_code}): {api_error(resp)}[/red]")
        raise typer.Exit(1)
    return payload(resp)


def _step(done: str) -> None:
    console.print(f"  [green]✓[/green] {done}")


def resolve_urls(control_plane_url: str, console_url: str) -> tuple[str, str]:
    """The control plane and the console, for the commands that print where the console lives."""
    return resolve_control_plane_url(control_plane_url), console_url or DEFAULT_CONSOLE_URL


class ProviderKey(NamedTuple):
    """What happened to one provider's key, so the command can say rather than summarise."""

    provider: str
    source: str
    error: str = ""


def _provider_key(name: str, overrides: dict[str, str]) -> tuple[str, str]:
    """The key for one provider and where it came from.

    Every provider is asked about, because the operator is the one who decides which of them this
    org spends against and an exported variable is a convenience rather than that decision. What is
    typed wins; blank falls back to the variable, so the common case is one keystroke and the
    prompt says which one it will take. Blank with nothing exported means no credential: a provider
    the org does not use should not have a key it cannot resolve.

    A flag answers ahead of the prompt, and without a terminal there is nobody to ask, so the
    variable stands on its own in scripts and containers.
    """
    if value := overrides.get(name):
        return value, "given on the command line"
    variable = f"{name.upper()}_API_KEY"
    exported = os.environ.get(variable, "")
    if not sys.stdin.isatty():
        return (exported, f"found in {variable}") if exported else ("", "")
    hint = f"blank to use {variable}" if exported else "blank to skip"
    typed = typer.prompt(f"  {name} API key ({hint})", default="", hide_input=True, show_default=False)
    if typed:
        return typed, "entered"
    return (exported, f"found in {variable}") if exported else ("", "")


def example_model(models: list[dict], seeded: set[str]) -> str:
    """The model the closing curl example names.

    The cheapest model a just-seeded provider serves: the printed command must work as pasted,
    and the first trial request should cost as little as a request can. With nothing seeded no
    model serves anyway, so the example settles for the cheapest spelling in the catalog."""
    routable = [model for model in models if model["provider_id"] in seeded] or models
    if not routable:
        return "openai/gpt-4o-mini"
    return min(routable, key=lambda model: (model.get("input_price_per_mtok") or 0.0, model["model_id"]))["model_id"]


def seed_provider_credentials(
    client: httpx.Client,
    bearer: dict[str, str],
    org_id: str,
    workspace: str,
    overrides: dict[str, str],
) -> list[ProviderKey]:
    """Give the workspace a key for every catalog provider one can be found for, and say what happened.

    A fresh install has a catalog and no credentials, which is a gateway that routes nothing, so
    this is what decides whether the command ends with something that serves. It reports per
    provider rather than in total, because which key came from where is what an operator needs to
    check, and a store that would not hold one has something to say about why.

    Scoped to the workspace the command just made, which is where the inference key it prints lives.
    The org tier is what a workspace falls back to when it brought nothing, so putting the first key
    there would make the fallback the only path and leave the tier the caller resolves through
    empty. A second workspace starts without a key, which is the question BYOK exists to ask.

    Seeds what it can: a deployment using only openai should not have to supply an anthropic key to
    finish setting up, and a provider without a key is skipped in silence rather than reported as a
    failure. Nothing here aborts the command, which has already created the account and the org.
    """
    catalog = client.get(f"/v1/orgs/{org_id}/taxonomy", headers=bearer)
    if not catalog.is_success:
        return []
    results = []
    for provider in catalog.json()["data"]["providers"]:
        name = provider["name"]
        value, source = _provider_key(name, overrides)
        if not value:
            continue
        body = {"provider": name, "value": value}
        created = client.post(f"/v1/orgs/{org_id}/workspaces/{workspace}/provider-credentials", json=body, headers=bearer)
        error = "" if created.is_success else api_error(created)
        results.append(ProviderKey(name, source, error))
    return results


@app.command(rich_help_panel=SETUP)
def quickstart(  # noqa: PLR0913, PLR0917 flags are the command's interface
    control_plane_url: str = "",
    email: str = typer.Option(..., prompt="Email", help="Email for the first account"),
    password: str = typer.Option(..., prompt="Password", hide_input=True, confirmation_prompt=True, help="At least 8 characters"),
    org: str = typer.Option("", help="Organization name; defaults to your email name"),
    gateway_url: str = typer.Option("http://localhost:8080", help="Gateway URL, used in the example at the end"),
    openai_key: str = typer.Option("", help="OpenAI key; otherwise read from OPENAI_API_KEY or prompted for"),
    anthropic_key: str = typer.Option("", help="Anthropic key; otherwise read from ANTHROPIC_API_KEY or prompted for"),
    console_url: str = typer.Option("", help="Web console URL, printed at the end"),
) -> None:
    """Set up a new instance: account, organization, workspace, provider keys, and an API key you can call."""
    import httpx  # noqa: PLC0415 lazy import keeps CLI startup fast

    url, console_url = resolve_urls(control_plane_url, console_url)
    console.print("[bold]airllm quickstart[/bold]")
    with httpx.Client(base_url=url, timeout=10.0, headers=CSRF) as c:
        if _payload_or_die(c.get("/v1/instance/oss/claim"), "claim check")["claimed"]:
            console.print(f"[red]{url} is already set up. Run [bold]airllm login[/bold] instead.[/red]")
            raise typer.Exit(1)

        _payload_or_die(c.post("/v1/auth/signup", json={"email": email, "name": email, "password": password}), "sign up")
        _step(f"Account [bold]{email}[/bold]")

        created = _payload_or_die(c.post("/v1/enroll/org", json={"name": org or email.split("@", maxsplit=1)[0]}), "org creation")
        org_id, org_name = created["id"], created["name"]
        _step(f"Organization [bold]{org_name}[/bold]")

        data_plane = _payload_or_die(
            c.post("/v1/service-accounts", json={"name": "data-plane", "instance_role": "data_plane"}),
            "data-plane principal creation",
        )
        data_plane_key = _payload_or_die(
            c.post(
                "/v1/instance/access-keys",
                json={
                    "label": "data-plane",
                    "user_id": data_plane["id"],
                    "permissions": DATA_PLANE_PERMISSIONS,
                },
            ),
            "data-plane key creation",
        )

        started = _payload_or_die(c.post("/v1/auth/cli/start", json={"client_name": _client_name()}), "access key request")
        _payload_or_die(c.post("/v1/auth/cli/approve", json={"user_code": started["user_code"], "org_id": org_id}), "access key approval")
        token = _payload_or_die(c.post("/v1/auth/cli/poll", json={"poll_secret": started["poll_secret"]}), "access key delivery")["token"]

        bearer = {"authorization": f"Bearer {token}"}
        workspace = _payload_or_die(c.post(f"/v1/orgs/{org_id}/workspaces", json={"name": "default"}, headers=bearer), "workspace creation")
        upsert_profile(
            org_name,
            {
                "control_plane_url": url,
                "console_url": console_url,
                "org_id": org_id,
                "org_name": org_name,
                "token": token,
                "workspace": workspace["slug"],
                "workspace_name": workspace["name"],
            },
        )
        _step(f"Workspace [bold]{workspace['name']}[/bold], signed in and saved to {config_path()}")

        quick = c.post("/v1/instance/oss/quickstart", json={"token": data_plane_key["token"]})
        if quick.is_success:
            _step("Connected your gateway")
        else:
            console.print(f"  [yellow]![/yellow] Could not connect your gateway ({quick.status_code}).")
            console.print(f"  Set GW_DATAPLANE_TOKEN={data_plane_key['token']}")

        key = _payload_or_die(
            c.post(f"/v1/orgs/{org_id}/workspaces/{workspace['id']}/inference-keys", json={"label": "quickstart"}, headers=bearer), "key mint"
        )
        overrides = {name: value for name, value in (("openai", openai_key), ("anthropic", anthropic_key)) if value}
        console.print("\n[dim]Provider keys. Press enter to skip a provider.[/dim]")
        results = seed_provider_credentials(c, bearer, org_id, workspace["slug"], overrides)
        for result in results:
            if result.error:
                console.print(f"  [yellow]![/yellow] {result.provider}: {result.error}")
            else:
                _step(f"[bold]{result.provider}[/bold] key {result.source}")
        if not any(not result.error for result in results):
            console.print("  [yellow]![/yellow] No provider key set. Add one with [bold]airllm provider-credentials add <provider>[/bold].")

        _payload_or_die(c.post(f"/v1/orgs/{org_id}/bundles/compile", json={}, headers=bearer), "publishing configuration")
        _step("API key created and published")

        catalog = c.get(f"/v1/orgs/{org_id}/taxonomy", headers=bearer)
        models = catalog.json()["data"]["models"] if catalog.is_success else []
        example = example_model(models, {result.provider for result in results if not result.error})

    curl = (
        f"curl {gateway_url}/v1/chat/completions \\\n"
        f"  -H 'Authorization: Bearer {key['token']}' \\\n"
        f"  -H 'Content-Type: application/json' \\\n"
        f'  -d \'{{"model": "{example}", "messages": [{{"role": "user", "content": "hi"}}]}}\''
    )
    console.print(f"\n[green]Ready.[/green] Your API key for [bold]{org_name}[/bold]:")
    console.print(Panel(key["token"], title="AIRLLM_API_KEY", border_style="cyan", expand=False))
    console.print("\n[dim]Try it:[/dim]")
    print(curl)
    console.print(f"\n[dim]Console:[/dim] {console_url}")


@app.command(rich_help_panel=SETUP)
def login(
    control_plane_url: str = "",
    no_browser: bool = typer.Option(False, "--no-browser", help="Print the URL instead of opening a browser"),
    console_url: str = typer.Option("", help="Web console URL"),
) -> None:
    """Sign in through your browser. Creates an account and organization if you do not have one."""
    import httpx  # noqa: PLC0415 lazy import keeps CLI startup fast

    url, console_url = resolve_urls(control_plane_url, console_url)
    client_name = _client_name()
    existing_access_key = _existing_access_key(url)
    with httpx.Client(base_url=url, timeout=10.0) as c:
        started = _payload_or_die(c.post("/v1/auth/cli/start", json={"client_name": client_name}), "Starting sign-in")
        console.print(f"Confirm code [bold]{started['user_code']}[/bold] at {started['verification_url']}")
        if not no_browser:
            webbrowser.open(started["verification_url"])
        deadline = time.monotonic() + started["expires_in_seconds"]
        while time.monotonic() < deadline:
            time.sleep(started["interval_seconds"])
            poll = c.post(
                "/v1/auth/cli/poll",
                json={"poll_secret": started["poll_secret"]},
                headers={"authorization": f"Bearer {existing_access_key}"} if existing_access_key else None,
            )
            if poll.status_code == HTTP_GONE:
                console.print("[red]Login expired before it was approved. Run [bold]airllm login[/bold] again.[/red]")
                raise typer.Exit(1)
            done = _payload_or_die(poll, "Sign-in")
            if done["status"] == "complete":
                upsert_profile(
                    done["org_name"],
                    {
                        "control_plane_url": url,
                        "console_url": console_url,
                        "org_id": done["org_id"],
                        "org_name": done["org_name"],
                        "token": done["token"],
                    },
                )
                console.print(f"Signed in to [bold]{done['org_name']}[/bold]. Saved to {config_path()}.")
                return
    console.print("[red]Login timed out. Run [bold]airllm login[/bold] again.[/red]")
    raise typer.Exit(1)


@orgs_app.command("switch")
def orgs_switch(name: str, control_plane_url: str = "") -> None:
    """Switch to another organization."""
    if os.environ.get("GW_ACCESS_KEY"):
        console.print("[yellow]GW_ACCESS_KEY is set and takes precedence. Unset it for this to take effect.[/yellow]")
    config = load_config()
    if name in (config.get("profiles") or {}):
        set_active(name)
        console.print(f"Switched to [bold]{name}[/bold]")
        return
    console.print(f"Not signed in to [bold]{name}[/bold]. Opening browser login, pick [bold]{name}[/bold] to approve.")
    login(control_plane_url=control_plane_url)
    active = load_config().get("active")
    if active != name:
        console.print(f"[yellow]You approved [bold]{active}[/bold], not {name}. It is now active.[/yellow]")


@orgs_app.command("mine")
def orgs_mine(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List the organizations you belong to."""
    from cli.client import access_client  # noqa: PLC0415 lazy import keeps CLI startup fast

    with access_client(control_plane_url) as c:
        resp = c.get("/v1/enroll")
        ensure_ok(resp)
        standing = payload(resp)
        rows = [{**org, "kind": "personal" if org["id"] == standing["personal_org_id"] else "member"} for org in standing["orgs"]]
        print_rows("orgs", rows, MINE_COLS, fmt)
