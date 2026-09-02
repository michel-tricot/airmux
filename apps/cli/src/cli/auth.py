from __future__ import annotations

import os
import socket
import sys
import time
import webbrowser
from typing import TYPE_CHECKING, NamedTuple

import typer
from pydantic import BaseModel
from rich.panel import Panel

from api_models import (
    AccessKeyMintedOut,
    ClaimOut,
    CliAuthApprovedOut,
    CliAuthPollOut,
    CliAuthStartOut,
    DataPlaneInstanceOut,
    EnrollOut,
    InferenceKeyMintedOut,
    MeOut,
    OrgOut,
    ProviderCredentialOut,
    TaxonomyOut,
    UserOut,
    WorkspaceOut,
)

if TYPE_CHECKING:
    import httpx

from cli.client import api_error, ensure_ok, payload, payload_rows, resolve_control_plane_url
from cli.common import SETUP, app, console, orgs_app
from cli.output import Col, FormatOption, OutputFormat, print_rows
from cli.profiles import (
    DEFAULT_CONSOLE_URL,
    Profile,
    config_path,
    load_active_profile,
    load_config,
    set_active,
    upsert_url_profile,
)

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
    profile = load_active_profile()
    if profile is None or (profile.control_plane_url or "").rstrip("/") != control_plane_url.rstrip("/"):
        return None
    return profile.token


def _payload_or_die[PayloadT: BaseModel](resp: httpx.Response, what: str, payload_type: type[PayloadT]) -> PayloadT:
    if not resp.is_success:
        console.print(f"[red]{what} failed ({resp.status_code}): {api_error(resp)}[/red]")
        raise typer.Exit(1)
    return payload(resp, payload_type)


def _step(done: str) -> None:
    console.print(f"  [green]✓[/green] {done}")


def resolve_urls(control_plane_url: str, console_url: str) -> tuple[str, str]:
    """The control plane and the console, for the commands that print where the console lives."""
    return resolve_control_plane_url(control_plane_url), console_url or DEFAULT_CONSOLE_URL


def resolve_login_urls(url: str, control_plane_url: str, console_url: str) -> tuple[str, str]:
    if url and (control_plane_url or console_url):
        msg = "--url cannot be combined with --control-plane-url or --console-url"
        raise typer.BadParameter(msg)
    if url:
        normalized = url.rstrip("/")
        return normalized, normalized
    return resolve_urls(control_plane_url, console_url)


class ProviderKey(NamedTuple):
    """What happened to one provider's key, so the command can say rather than summarise."""

    provider: str
    source: str
    error: str = ""


def _provider_key(name: str, overrides: dict[str, str]) -> tuple[str, str]:
    """The key for one provider and where it came from.

    Every provider is asked about, because the operator is the one who decides which of them this
    instance spends against and an exported variable is a convenience rather than that decision. What is
    typed wins; blank falls back to the variable, so the common case is one keystroke and the
    prompt says which one it will take. Blank with nothing exported means no credential: a provider
    the instance does not use should not have a key it cannot resolve.

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


def seed_provider_credentials(
    client: httpx.Client,
    overrides: dict[str, str],
) -> list[ProviderKey]:
    """Give the instance a key for every catalog provider one can be found for, and say what happened.

    A fresh install has a catalog and no credentials, which is a gateway that routes nothing, so
    this is what decides whether the command ends with something that serves. It reports per
    provider rather than in total, because which key came from where is what an operator needs to
    check, and a store that would not hold one has something to say about why.

    Scoped to the instance so the first provider keys are global defaults. Every organization and
    workspace can use them unless it configures provider credentials at a more specific tier.

    Seeds what it can: a deployment using only openai should not have to supply an anthropic key to
    finish setting up, and a provider without a key is skipped in silence rather than reported as a
    failure. Nothing here aborts the command, which has already created the account and the org.
    """
    catalog = client.get("/api/v1/instance/taxonomy")
    if not catalog.is_success:
        return []
    credentials = client.get("/api/v1/instance/provider-credentials")
    existing = (
        {credential.provider_name: credential.enabled for credential in payload_rows(credentials, ProviderCredentialOut)}
        if credentials.is_success
        else {}
    )
    results = []
    for provider in payload(catalog, TaxonomyOut).providers:
        name = provider.name
        if name in existing:
            results.append(ProviderKey(name, "already configured", "" if existing[name] else "credential exists but is disabled"))
            continue
        value, source = _provider_key(name, overrides)
        if not value:
            continue
        body = {"provider": name, "value": value}
        created = client.post("/api/v1/instance/provider-credentials", json=body)
        error = "" if created.is_success else api_error(created)
        results.append(ProviderKey(name, source, error))
    return results


def configured_model(client: httpx.Client) -> str | None:
    catalog = client.get("/api/v1/instance/taxonomy")
    credentials = client.get("/api/v1/instance/provider-credentials")
    if not catalog.is_success or not credentials.is_success:
        return None
    taxonomy = payload(catalog, TaxonomyOut)
    configured = {credential.provider_name for credential in payload_rows(credentials, ProviderCredentialOut) if credential.enabled}
    provider_ids = {provider.id for provider in taxonomy.providers if provider.name in configured}
    models = sorted(model.name for model in taxonomy.models if model.provider_id in provider_ids)
    return models[0] if models else None


def _login_or_signup(client: httpx.Client, claimed: bool, email: str, password: str) -> None:
    if claimed:
        account = _payload_or_die(client.post("/api/v1/auth/login", json={"email": email, "password": password}), "sign in", MeOut)
        if account.instance_role is None or account.instance_role.root != "owner":
            console.print("[red]Quickstart requires the instance owner account.[/red]")
            raise typer.Exit(1)
        _step(f"Signed in as [bold]{email}[/bold]")
        return
    _payload_or_die(client.post("/api/v1/auth/signup", json={"email": email, "name": email, "password": password}), "sign up", MeOut)
    _step(f"Account [bold]{email}[/bold]")


def _personal_org(client: httpx.Client, email: str, requested_name: str) -> OrgOut:
    enrollment = _payload_or_die(client.get("/api/v1/enroll"), "organization lookup", EnrollOut)
    existing = next((organization for organization in enrollment.orgs if organization.id == enrollment.personal_org_id), None)
    if existing is not None:
        _step(f"Organization [bold]{existing.name}[/bold]")
        return existing
    organization = _payload_or_die(
        client.post("/api/v1/enroll/org", json={"name": requested_name or email.split("@", maxsplit=1)[0]}),
        "org creation",
        OrgOut,
    )
    _step(f"Organization [bold]{organization.name}[/bold]")
    return organization


def _organization_access_key(client: httpx.Client, org_id: str) -> str:
    started = _payload_or_die(client.post("/api/v1/auth/cli/start", json={"client_name": _client_name()}), "access key request", CliAuthStartOut)
    _payload_or_die(
        client.post(
            "/api/v1/auth/cli/approve",
            json={"user_code": started.user_code, "scope": "org", "org_id": org_id},
        ),
        "access key approval",
        CliAuthApprovedOut,
    )
    delivered = _payload_or_die(
        client.post(
            "/api/v1/auth/cli/poll",
            json={"poll_secret": started.poll_secret},
        ),
        "access key delivery",
        CliAuthPollOut,
    )
    if delivered.status != "complete" or delivered.scope != "org" or delivered.token is None:
        console.print("[red]Access key delivery returned an incomplete response.[/red]")
        raise typer.Exit(1)
    return delivered.token


def _default_workspace(client: httpx.Client, org_id: str, bearer: dict[str, str]) -> WorkspaceOut:
    listed = payload_rows(ensure_ok(client.get(f"/api/v1/orgs/{org_id}/workspaces", headers=bearer)), WorkspaceOut)
    workspace = next((candidate for candidate in listed if candidate.slug == "default"), None)
    if workspace is None:
        workspace = _payload_or_die(
            client.post(f"/api/v1/orgs/{org_id}/workspaces", json={"name": "default"}, headers=bearer),
            "workspace creation",
            WorkspaceOut,
        )
    return workspace


def _install_data_plane_key(client: httpx.Client) -> str | None:
    instances = payload_rows(ensure_ok(client.get("/api/v1/instance/data-planes", params={"include_offline": True})), DataPlaneInstanceOut)
    if instances:
        _step("Gateway already connected")
        return None
    users = payload_rows(ensure_ok(client.get("/api/v1/users", params={"service_account": True})), UserOut)
    data_plane = next((user for user in users if user.name == "data-plane" and user.instance_role == "data_plane"), None)
    if data_plane is None:
        data_plane = _payload_or_die(
            client.post("/api/v1/service-accounts", json={"name": "data-plane", "instance_role": "data_plane"}),
            "data-plane principal creation",
            UserOut,
        )
    data_plane_key = _payload_or_die(
        client.post(
            "/api/v1/instance/access-keys",
            json={"label": "data-plane", "user_id": str(data_plane.id), "permissions": DATA_PLANE_PERMISSIONS},
        ),
        "data-plane key creation",
        AccessKeyMintedOut,
    )
    connected = client.post("/api/v1/instance/oss/quickstart", json={"token": data_plane_key.token})
    if connected.is_success:
        _step("Connected your gateway")
        return None
    console.print(f"  [yellow]![/yellow] Could not connect your gateway ({connected.status_code}: {api_error(connected)})")
    return data_plane_key.token


def _inference_key(client: httpx.Client, org_id: str, workspace: WorkspaceOut, bearer: dict[str, str]) -> InferenceKeyMintedOut:
    path = f"/api/v1/orgs/{org_id}/workspaces/{workspace.id}/inference-keys"
    return _payload_or_die(client.post(path, json={"label": "quickstart"}, headers=bearer), "key mint", InferenceKeyMintedOut)


def _gateway_error(response: httpx.Response) -> str:
    try:
        body = response.json()
        error = body.get("error") or {}
        return str(error.get("message") or error.get("code") or body.get("detail") or body.get("status") or response.text)
    except (ValueError, AttributeError):
        return response.text or response.reason_phrase


def verify_gateway(gateway_url: str, token: str, model: str) -> str:
    import httpx  # noqa: PLC0415 lazy import keeps CLI startup fast

    with httpx.Client(base_url=gateway_url.rstrip("/"), timeout=30.0) as gateway:
        for _ in range(20):
            try:
                ready = gateway.get("/readyz", timeout=2.0)
            except httpx.HTTPError:
                ready = None
            if ready is not None and ready.is_success:
                break
            time.sleep(0.5)
        else:
            return "gateway did not become ready"
        try:
            response = gateway.post(
                "/inf/v1/chat/completions",
                headers={"authorization": f"Bearer {token}", "x-airllm-dialect": "canonical"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": [{"type": "text", "text": "Reply with exactly: airllm ready"}]}],
                    "stream": False,
                },
            )
        except httpx.HTTPError as error:
            return str(error)
    return "" if response.is_success else f"HTTP {response.status_code}: {_gateway_error(response)}"


def _curl(gateway_url: str, token: str, model: str) -> str:
    return (
        f"curl {gateway_url.rstrip('/')}/inf/v1/chat/completions \\\n"
        f"  -H 'Authorization: Bearer {token}' \\\n"
        "  -H 'Content-Type: application/json' \\\n"
        "  -H 'x-airllm-dialect: canonical' \\\n"
        f'  -d \'{{"model": "{model}", "messages": [{{"role": "user", "content": [{{"type": "text", "text": "hi"}}]}}]}}\''
    )


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
    """Set up or resume an instance and verify a new API key through the gateway."""
    import httpx  # noqa: PLC0415 lazy import keeps CLI startup fast

    url, console_url = resolve_urls(control_plane_url, console_url)
    console.print("[bold]airllm quickstart[/bold]")
    with httpx.Client(base_url=url, timeout=10.0, headers=CSRF) as c:
        claimed = _payload_or_die(c.get("/api/v1/instance/oss/claim"), "claim check", ClaimOut).claimed
        _login_or_signup(c, claimed, email, password)
        organization = _personal_org(c, email, org)
        org_id, org_name = organization.id, organization.name
        token = _organization_access_key(c, str(org_id))
        bearer = {"authorization": f"Bearer {token}"}
        workspace = _default_workspace(c, str(org_id), bearer)
        upsert_url_profile(
            org_name,
            Profile(
                scope="org",
                control_plane_url=url,
                console_url=console_url,
                gateway_url=gateway_url.rstrip("/"),
                org_id=str(org_id),
                org_name=str(org_name),
                token=str(token),
                workspace=workspace.slug,
                workspace_name=workspace.name,
            ),
        )
        _step(f"Workspace [bold]{workspace.name}[/bold], signed in and saved to {config_path()}")
        data_plane_token = _install_data_plane_key(c)
        key = _inference_key(c, str(org_id), workspace, bearer)
        _step("API key created")
        console.print(f"\nYour API key for [bold]{org_name}[/bold], shown once:")
        console.print(Panel(key.token, title="AIRLLM_API_KEY", border_style="cyan", expand=False))
        overrides = {name: value for name, value in (("openai", openai_key), ("anthropic", anthropic_key)) if value}
        console.print("\n[dim]Global provider keys. Press enter to skip a provider.[/dim]")
        results = seed_provider_credentials(c, overrides)
        for result in results:
            if result.error:
                console.print(f"  [yellow]![/yellow] {result.provider}: {result.error}")
            else:
                _step(f"[bold]{result.provider}[/bold] key {result.source}")
        if not any(not result.error for result in results):
            console.print("  [yellow]![/yellow] No global provider key set. Add one in the instance console.")
        model = configured_model(c)

    if data_plane_token:
        console.print(f"  Set GW_DATAPLANE_TOKEN={data_plane_token}")
    if model is None:
        console.print("\n[red]Setup is incomplete: no model has a configured provider credential.[/red]")
        console.print("Enable or add a provider key, then run [bold]airllm quickstart[/bold] again.")
        raise typer.Exit(1)
    error = verify_gateway(gateway_url, key.token, model)
    if error:
        console.print(f"\n[red]Setup is incomplete: the gateway request failed: {error}[/red]")
        console.print("Run [bold]airllm doctor[/bold] after resolving the reported gateway issue.")
        raise typer.Exit(1)

    console.print(f"\n[green]Ready.[/green] Verified [bold]{model}[/bold] through the gateway.")
    console.print("\n[dim]Try it:[/dim]")
    print(_curl(gateway_url, key.token, model))
    console.print(f"\n[dim]Console:[/dim] {console_url}")


@app.command(rich_help_panel=SETUP)
def login(
    url: str = typer.Option("", "--url", help="URL serving both the control plane API and web console"),
    control_plane_url: str = typer.Option("", help="Control plane API URL, for split development deployments"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Print the URL instead of opening a browser"),
    console_url: str = typer.Option("", help="Web console URL, for split development deployments"),
    gateway_url: str = typer.Option("", help="Gateway URL, for split deployments"),
) -> None:
    """Sign in through your browser. Creates an account and organization if you do not have one."""
    import httpx  # noqa: PLC0415 lazy import keeps CLI startup fast

    control_plane_url, console_url = resolve_login_urls(url, control_plane_url, console_url)
    gateway_url = (gateway_url or url or "http://localhost:8080").rstrip("/")
    client_name = _client_name()
    existing_access_key = _existing_access_key(control_plane_url)
    with httpx.Client(base_url=control_plane_url, timeout=10.0) as c:
        started = _payload_or_die(c.post("/api/v1/auth/cli/start", json={"client_name": client_name}), "Starting sign-in", CliAuthStartOut)
        console.print(f"Confirm code [bold]{started.user_code}[/bold] at {started.verification_url}")
        if not no_browser:
            webbrowser.open(started.verification_url)
        deadline = time.monotonic() + started.expires_in_seconds
        while time.monotonic() < deadline:
            time.sleep(started.interval_seconds)
            poll = c.post(
                "/api/v1/auth/cli/poll",
                json={"poll_secret": started.poll_secret},
                headers={"authorization": f"Bearer {existing_access_key}"} if existing_access_key else None,
            )
            if poll.status_code == HTTP_GONE:
                console.print("[red]Login expired before it was approved. Run [bold]airllm login[/bold] again.[/red]")
                raise typer.Exit(1)
            ensure_ok(poll)
            done = payload(poll, CliAuthPollOut)
            if done.status == "complete":
                if done.scope == "org" and done.token is not None and done.org_id is not None and done.org_name is not None:
                    target_name = done.org_name
                    profile = Profile(
                        scope="org",
                        control_plane_url=control_plane_url,
                        console_url=console_url,
                        gateway_url=gateway_url,
                        token=done.token,
                        org_id=str(done.org_id),
                        org_name=done.org_name,
                    )
                elif done.scope == "instance" and done.token is not None:
                    target_name = "instance"
                    profile = Profile(
                        scope="instance",
                        control_plane_url=control_plane_url,
                        console_url=console_url,
                        gateway_url=gateway_url,
                        token=done.token,
                    )
                else:
                    console.print("[red]Sign-in returned an incomplete profile.[/red]")
                    raise typer.Exit(1)
                profile_name = upsert_url_profile(target_name, profile)
                console.print(f"Signed in to [bold]{target_name}[/bold] as profile [bold]{profile_name}[/bold]. Saved to {config_path()}.")
                return
    console.print("[red]Login timed out. Run [bold]airllm login[/bold] again.[/red]")
    raise typer.Exit(1)


@orgs_app.command("switch")
def orgs_switch(name: str, control_plane_url: str = "") -> None:
    """Switch to another organization."""
    if os.environ.get("GW_ACCESS_KEY"):
        console.print("[yellow]GW_ACCESS_KEY is set and takes precedence. Unset it for this to take effect.[/yellow]")
    config = load_config()
    if name in config.profiles:
        set_active(name)
        console.print(f"Switched to [bold]{name}[/bold]")
        return
    console.print(f"Not signed in to [bold]{name}[/bold]. Opening browser login, pick [bold]{name}[/bold] to approve.")
    login(url="", control_plane_url=control_plane_url, no_browser=False, console_url="", gateway_url="")
    active = load_config().active
    if active != name:
        console.print(f"[yellow]You approved [bold]{active}[/bold], not {name}. It is now active.[/yellow]")


@orgs_app.command("mine")
def orgs_mine(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List the organizations you belong to."""
    from cli.client import access_client  # noqa: PLC0415 lazy import keeps CLI startup fast

    with access_client(control_plane_url) as c:
        resp = c.get("/api/v1/enroll")
        ensure_ok(resp)
        standing = payload(resp, EnrollOut)
        rows = [{**org.model_dump(mode="json"), "kind": "personal" if org.id == standing.personal_org_id else "member"} for org in standing.orgs]
        print_rows("orgs", rows, MINE_COLS, fmt)
