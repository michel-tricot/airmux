from __future__ import annotations

import json
import sys
import time
from collections import deque
from typing import TYPE_CHECKING, Annotated

import typer
from dotenv import find_dotenv, load_dotenv
from rich.live import Live

from cli.client import (
    ensure_ok,
    instance_client,
    instance_get,
    org_client,
    org_get,
    payload,
    payload_rows,
    post_expecting,
    resolve_workspace,
)
from cli.common import (
    ADMIN,
    bundles_app,
    console,
    data_planes_app,
    events_app,
    inference_keys_app,
    instance_keys_app,
    management_keys_app,
    models_app,
    org_members_app,
    orgs_app,
    provider_credentials_app,
    providers_app,
    service_accounts_app,
    users_app,
    workspace_members_app,
    workspaces_app,
)
from cli.forms import register_create
from cli.output import Col, FormatOption, OutputFormat, build_table, fmt_when, print_rows
from cli.profiles import active_profile, upsert_profile

if TYPE_CHECKING:
    from rich.table import Table
from cli.specs import ModelCreate, OrgCreate, ProviderCreate

ORG_COLS = [
    Col("id", "ID", style="dim", no_wrap=True),
    Col("name", "Name", max_width=40),
    Col("created_at", "Created", no_wrap=True, fmt=fmt_when),
]
KEY_COLS = [
    Col("id", "ID", style="dim", no_wrap=True),
    Col("label", "Label", max_width=30),
    Col("workspace_id", "Workspace"),
    Col("user_id", "Owner", style="dim", no_wrap=True),
    Col("revoked", "Status", style="yellow", fmt=lambda v: "revoked" if v else "active"),
    Col("created_at", "Created", no_wrap=True, fmt=fmt_when),
]
WORKSPACE_COLS = [
    Col("id", "ID", style="dim", no_wrap=True),
    Col("slug", "Slug", max_width=40),
    Col("name", "Name", max_width=40),
    Col("created_at", "Created", no_wrap=True, fmt=fmt_when),
]
MEMBER_COLS = [
    Col("user_id", "User", style="dim", no_wrap=True),
    Col("status", "Status", style="yellow"),
]
PROVIDER_COLS = [
    Col("id", "ID", style="dim", no_wrap=True),
    Col("kind", "Kind"),
    Col("base_url", "Base URL", max_width=45),
]
MODEL_COLS = [
    Col("id", "ID", style="dim", no_wrap=True),
    Col("provider_id", "Provider"),
    Col("upstream_model", "Upstream model"),
    Col("input_price_per_mtok", "$/Mtok in"),
    Col("output_price_per_mtok", "$/Mtok out"),
    Col("cache_read_price_per_mtok", "$/Mtok cache read"),
    Col("cache_write_price_per_mtok", "$/Mtok cache write"),
    Col("context_window", "Context"),
    Col("max_output_tokens", "Max out"),
    Col("capabilities", "Capabilities", style="cyan", max_width=30),
]


CREDENTIAL_HEALTH_LABELS = {"unknown": "unused", "live": "working", "invalid": "rejected", "rate_limited": "throttled"}
"""What the data plane last saw of a key, said the way an operator would say it."""


def _credential_rows(rows: list[dict]) -> list[dict]:
    """Fold enabled into health: a disabled key is out of the pool whatever its last request said,
    so that is the one fact worth a column."""
    return [{**row, "health": "disabled" if not row["enabled"] else CREDENTIAL_HEALTH_LABELS.get(row["status"], row["status"])} for row in rows]


def _money(value: object) -> str:
    return f"{value:.6f}" if isinstance(value, int | float) else str(value or "")


EVENT_COLS = [
    Col("occurred_at", "When", no_wrap=True, fmt=lambda v: str(v)[:19].replace("T", " ")),
    Col("request_id", "Request", style="dim", no_wrap=True, fmt=lambda v: str(v)[:8]),
    Col("workspace_id", "Workspace", style="dim", no_wrap=True, fmt=lambda v: str(v)[:8]),
    Col("model_id", "Model"),
    Col("status", "Status", style="yellow"),
    Col("input_tokens", "In"),
    Col("output_tokens", "Out"),
    Col("cache_read_tokens", "Cached", fmt=lambda v: str(v) if v else ""),
    Col("cost_input_usd", "$ in", fmt=_money),
    Col("cost_output_usd", "$ out", fmt=_money),
    Col("cost_usd", "$ total", fmt=_money),
    Col("latency_ms", "ms"),
    Col("stream", "Stream", fmt=lambda v: "yes" if v else ""),
]
BUNDLE_COLS = [
    Col("id", "ID", style="dim", no_wrap=True, fmt=lambda v: str(v)[:8]),
    Col("org_id", "Org"),
    Col("version", "Version"),
    Col("issued_at", "Issued", no_wrap=True, fmt=fmt_when),
    Col("expires_at", "Expires", no_wrap=True, fmt=fmt_when),
    Col("signing_key_id", "Key", style="dim"),
]


@orgs_app.command("list", rich_help_panel=ADMIN)
def orgs_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List every organization on this instance."""
    print_rows("orgs", instance_get("/v1/orgs", control_plane_url), ORG_COLS, fmt)


WorkspaceOption = Annotated[str, typer.Option("--workspace", "-w", help="Workspace name or id; defaults to your selected workspace")]


@workspaces_app.command("list")
def workspaces_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List your workspaces."""
    print_rows("workspaces", org_get("/v1/org/workspaces", control_plane_url), WORKSPACE_COLS, fmt)


@workspaces_app.command("use")
def workspaces_use(workspace: str, control_plane_url: str = "") -> None:
    """Select the workspace that key commands use by default."""
    profile = active_profile()
    if profile is None:
        console.print("[red]Not signed in. Run [bold]airllm login[/bold].[/red]")
        raise typer.Exit(1)
    with org_client(control_plane_url) as c:
        resp = c.get(f"/v1/org/workspaces/{workspace}")
    if not resp.is_success:
        console.print(f"[red]No workspace [bold]{workspace}[/bold]. See [bold]airllm workspaces list[/bold].[/red]")
        raise typer.Exit(1)
    chosen = payload(resp)
    name = str(profile.pop("name"))
    upsert_profile(name, {**profile, "workspace": chosen["slug"], "workspace_name": chosen["name"]})
    console.print(f"Using workspace [bold]{chosen['slug']}[/bold]")


@workspace_members_app.command("list")
def workspace_members_list(workspace: WorkspaceOption = "", control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List who can use this workspace."""
    workspace_ref = resolve_workspace(workspace)
    print_rows("members", org_get(f"/v1/org/workspaces/{workspace_ref}/members", control_plane_url), MEMBER_COLS, fmt)


@workspace_members_app.command("add")
def workspace_members_add(user_id: str, workspace: WorkspaceOption = "", control_plane_url: str = "") -> None:
    """Give someone access to this workspace."""
    workspace_ref = resolve_workspace(workspace)
    with org_client(control_plane_url) as c:
        resp = c.put(f"/v1/org/workspaces/{workspace_ref}/members/{user_id}")
        ensure_ok(resp)
    console.print(f"Added [bold]{user_id}[/bold] to [bold]{workspace_ref}[/bold]")


@workspace_members_app.command("remove")
def workspace_members_remove(user_id: str, workspace: WorkspaceOption = "", control_plane_url: str = "") -> None:
    """Remove a member from a workspace; their keys there keep working until revoked."""
    workspace_ref = resolve_workspace(workspace)
    with org_client(control_plane_url) as c:
        resp = c.delete(f"/v1/org/workspaces/{workspace_ref}/members/{user_id}")
        ensure_ok(resp)
    console.print(f"Removed [bold]{user_id}[/bold] from [bold]{workspace_ref}[/bold]")


@inference_keys_app.command("list")
def inference_keys_list(workspace: WorkspaceOption = "", control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List this workspace's API keys."""
    workspace_ref = resolve_workspace(workspace)
    print_rows("inference keys", org_get(f"/v1/org/workspaces/{workspace_ref}/inference-keys", control_plane_url), KEY_COLS, fmt)


@inference_keys_app.command("revoke")
def inference_keys_revoke(key_id: str, workspace: WorkspaceOption = "", control_plane_url: str = "") -> None:
    """Revoke an API key."""
    workspace_ref = resolve_workspace(workspace)
    with org_client(control_plane_url) as c:
        resp = c.delete(f"/v1/org/workspaces/{workspace_ref}/inference-keys/{key_id}")
        ensure_ok(resp)
    console.print(f"Revoked [bold]{key_id}[/bold]")


_SCOPES_COL = Col("scopes", "Scopes", style="cyan", max_width=40, fmt=lambda v: ", ".join(map(str, v)) if isinstance(v, list) else "all")
_STATUS_COL = Col("revoked", "Status", style="yellow", fmt=lambda v: "revoked" if v else "active")

MANAGEMENT_KEY_COLS = [
    Col("id", "ID", style="dim", no_wrap=True),
    Col("label", "Label", max_width=30),
    Col("org_id", "Org", no_wrap=True),
    Col("user_id", "Owner", style="dim", fmt=lambda v: str(v) if v else "system"),
    _SCOPES_COL,
    _STATUS_COL,
    Col("created_at", "Created", no_wrap=True, fmt=fmt_when),
]

INSTANCE_KEY_COLS = [
    Col("id", "ID", style="dim", no_wrap=True),
    Col("label", "Label", max_width=30),
    Col("user_id", "Owner", style="dim", fmt=lambda v: str(v) if v else "system"),
    _SCOPES_COL,
    _STATUS_COL,
    Col("created_at", "Created", no_wrap=True, fmt=fmt_when),
]

USER_COLS = [
    Col("id", "ID", style="dim", no_wrap=True),
    Col("email", "Email"),
    Col("name", "Name", max_width=30),
    Col("service_account", "Kind", fmt=lambda v: "service" if v else "human"),
    Col("orgs", "Orgs", style="cyan", max_width=40),
    Col("created_at", "Created", no_wrap=True, fmt=fmt_when),
]

ORG_MEMBER_COLS = [
    Col("user_id", "ID", style="dim", no_wrap=True),
    Col("email", "Email"),
    Col("name", "Name", max_width=30),
    Col("service_account", "Kind", fmt=lambda v: "service" if v else "human"),
    Col("status", "Status", style="yellow"),
]


@users_app.command("create")
def users_create(
    email: str,
    name: str = "",
    control_plane_url: str = "",
) -> None:
    """Create an account. Add it to an organization with airllm orgs members add."""
    body = {"email": email, "name": name}
    with instance_client(control_plane_url) as c:
        resp = payload(post_expecting(c, "/v1/users", body, ok=(200,)))
    console.print(f"Created [bold]{resp['email']}[/bold]")


@service_accounts_app.command("create")
def service_accounts_create(
    name: str | None = typer.Argument(None, help="Service account name; prompted for when omitted"),
    control_plane_url: str = "",
) -> None:
    """Create a machine account for CI or automation."""
    if not name:
        name = typer.prompt("name")
    with instance_client(control_plane_url) as c:
        resp = payload(post_expecting(c, "/v1/service-accounts", {"name": name}, ok=(200,)))
    console.print(f"Created service account [bold]{resp['email']}[/bold]")
    console.print(f"[dim]Add it to your organization: airllm orgs members add {resp['id']}[/dim]")


@service_accounts_app.command("list")
def service_accounts_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List machine accounts."""
    rows = instance_get("/v1/users", control_plane_url, {"service_account": True})
    print_rows("service accounts", rows, USER_COLS, fmt)


@users_app.command("list")
def users_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List every account and the organizations it belongs to."""
    print_rows("users", instance_get("/v1/users", control_plane_url), USER_COLS, fmt)


@org_members_app.command("list")
def org_members_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List the active org's members."""
    print_rows("members", org_get("/v1/org/users", control_plane_url), ORG_MEMBER_COLS, fmt)


@org_members_app.command("add")
def org_members_add(user_id: str, control_plane_url: str = "") -> None:
    """Add a user to the active org; their org management keys start working immediately."""
    with org_client(control_plane_url) as c:
        resp = c.put(f"/v1/org/users/{user_id}")
        ensure_ok(resp)
    console.print(f"Added [bold]{user_id}[/bold] to your organization")


@org_members_app.command("remove")
def org_members_remove(user_id: str, control_plane_url: str = "") -> None:
    """Remove a user from the active org; their management keys for it stop working immediately."""
    with org_client(control_plane_url) as c:
        resp = c.delete(f"/v1/org/users/{user_id}")
        ensure_ok(resp)
    console.print(f"Removed [bold]{user_id}[/bold] from your organization")


@management_keys_app.command("list")
def management_keys_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List your automation keys."""
    print_rows("management keys", org_get("/v1/org/management-keys", control_plane_url), MANAGEMENT_KEY_COLS, fmt)


@management_keys_app.command("mint")
def management_keys_mint(
    label: str = typer.Option(..., "--label", help="What this key is for, e.g. ci"),
    user: str = typer.Option("", "--user", help="Who the key belongs to; defaults to you"),
    scope: Annotated[list[str] | None, typer.Option("--scope", help="Limit what the key can do, repeatable (e.g. inference-keys:read)")] = None,
    control_plane_url: str = "",
) -> None:
    """Create an automation key. Shown once, never stored."""
    body = {"user_id": user or None, "scopes": scope or None, "label": label}
    with org_client(control_plane_url) as c:
        resp = payload(post_expecting(c, "/v1/org/management-keys", body, ok=(200,)))
    restriction = f" restricted to {', '.join(resp['scopes'])}" if resp.get("scopes") else ""
    console.print(
        f"management key [bold]{resp['id']}[/bold] minted for [bold]{resp['org_id']}[/bold] "
        f"for user [bold]{resp['user_id']}[/bold]{restriction}, secret (shown once):"
    )
    console.print(resp["token"])


@management_keys_app.command("revoke")
def management_keys_revoke(key_id: str, control_plane_url: str = "") -> None:
    """Revoke an automation key."""
    with org_client(control_plane_url) as c:
        resp = c.delete(f"/v1/org/management-keys/{key_id}")
        ensure_ok(resp)
    console.print(f"Revoked [bold]{key_id}[/bold]")


@instance_keys_app.command("list")
def instance_keys_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List admin keys."""
    print_rows("instance keys", instance_get("/v1/instance/instance-keys", control_plane_url), INSTANCE_KEY_COLS, fmt)


@instance_keys_app.command("mint")
def instance_keys_mint(
    label: str = typer.Option(..., "--label", help="What this key is for, e.g. ci"),
    user: str = typer.Option("", "--user", help="Who the key belongs to; defaults to you"),
    scope: Annotated[list[str] | None, typer.Option("--scope", help="Limit what the key can do, repeatable (e.g. sync)")] = None,
    control_plane_url: str = "",
) -> None:
    """Create an admin key. Shown once, never stored."""
    body = {"user_id": user or None, "scopes": scope or None, "label": label}
    with instance_client(control_plane_url) as c:
        resp = payload(post_expecting(c, "/v1/instance/instance-keys", body, ok=(200,)))
    restriction = f" restricted to {', '.join(resp['scopes'])}" if resp.get("scopes") else ""
    console.print(f"New admin key for [bold]{resp['user_id']}[/bold]{restriction}, shown once:")
    console.print(resp["token"])


@instance_keys_app.command("revoke")
def instance_keys_revoke(key_id: str, control_plane_url: str = "") -> None:
    """Revoke an admin key."""
    with instance_client(control_plane_url) as c:
        resp = c.delete(f"/v1/instance/instance-keys/{key_id}")
        ensure_ok(resp)
    console.print(f"Revoked [bold]{key_id}[/bold]")


def _taxonomy(control_plane_url: str) -> dict:
    with org_client(control_plane_url) as c:
        resp = c.get("/v1/taxonomy")
        ensure_ok(resp)
        return payload(resp)


@providers_app.command("list")
def providers_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List the providers you can route to."""
    print_rows("providers", _taxonomy(control_plane_url)["providers"], PROVIDER_COLS, fmt)


@models_app.command("list")
def models_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List the models you can route to, with pricing."""
    print_rows("models", _taxonomy(control_plane_url)["models"], MODEL_COLS, fmt)


@bundles_app.command("list")
def bundles_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List published configuration versions."""
    print_rows("bundles", org_get("/v1/org/bundles", control_plane_url), BUNDLE_COLS, fmt)


@bundles_app.command("compile")
def bundles_compile(control_plane_url: str = "") -> None:
    """Publish your current configuration to your gateways."""
    with org_client(control_plane_url) as c:
        compiled = payload(post_expecting(c, "/v1/org/bundles/compile", {}, ok=(200,)))
    console.print(f"Published v{compiled['version']}")


INSTANCE_COLS = [
    Col("instance_id", "Instance", style="dim", no_wrap=True, fmt=lambda v: str(v)[:12]),
    Col("status", "Status", style="yellow"),
    Col("version", "Version"),
    Col("bundle_id", "Bundle", style="dim", fmt=lambda v: str(v)[:8] if v else ""),
    Col("address", "Address"),
    Col("last_seen", "Last seen", no_wrap=True, fmt=fmt_when),
]


@data_planes_app.command("list")
def data_planes_list(
    all_: bool = typer.Option(False, "--all", help="Include gateways that are offline"),
    control_plane_url: str = "",
    fmt: FormatOption = OutputFormat.table,
) -> None:
    """List connected gateways."""
    load_dotenv(find_dotenv(usecwd=True))
    with instance_client(control_plane_url) as c:
        resp = c.get("/v1/instance/data-planes", params={"include_offline": all_})
        ensure_ok(resp)
        print_rows("data planes", payload_rows(resp), INSTANCE_COLS, fmt)


@events_app.command("list")
def events_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List recent requests, newest first."""
    print_rows("events", org_get("/v1/org/events", control_plane_url), EVENT_COLS, fmt)


@events_app.command("tail")
def events_tail(interval: float = 2.0, keep: int = 30, control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """Follow requests as they happen."""
    rows: deque[dict] = deque(maxlen=keep)
    fresh_ids: set[str] = set()

    def table() -> Table:
        return build_table(list(rows), EVENT_COLS, lambda r: "blink bold cyan" if r["event_id"] in fresh_ids else None)

    def emit(event: dict) -> None:
        if fmt is OutputFormat.json:
            print(json.dumps(event, ensure_ascii=False), flush=True)
        else:
            print("\t".join(c.fmt(event.get(c.key)) for c in EVENT_COLS), flush=True)

    with org_client(control_plane_url) as c:
        resp = c.get("/v1/org/events", params={"limit": keep})
        ensure_ok(resp)
        rows.extend(reversed(payload_rows(resp)))
        cursor = rows[-1]["occurred_at"] if rows else "1970-01-01T00:00:00"
        try:
            if fmt is not OutputFormat.table:
                while True:
                    time.sleep(interval)
                    resp = c.get("/v1/org/events", params={"after": cursor, "limit": 200})
                    ensure_ok(resp)
                    for event in payload_rows(resp):
                        emit(event)
                        cursor = event["occurred_at"]
            with Live(table(), console=console, refresh_per_second=4) as live:
                while True:
                    time.sleep(interval)
                    resp = c.get("/v1/org/events", params={"after": cursor, "limit": 200})
                    ensure_ok(resp)
                    batch = payload_rows(resp)
                    fresh_ids = {event["event_id"] for event in batch}
                    if batch:
                        rows.extend(batch)
                        cursor = batch[-1]["occurred_at"]
                    live.update(table())
        except KeyboardInterrupt:
            console.print("[dim]stopped[/dim]")


def _key_created(resp: dict) -> None:
    console.print("Your new key, shown once:")
    console.print(resp["token"])
    console.print("[dim]Run airllm bundles compile to apply.[/dim]")


register_create(
    orgs_app,
    OrgCreate,
    "/v1/orgs",
    "Create an organization.",
    lambda resp: console.print(f"Created [bold]{resp['name']}[/bold]. Add people with airllm orgs members add <user>."),
    client=instance_client,
    panel=ADMIN,
)


@inference_keys_app.command("create")
def inference_keys_create(
    label: str = typer.Argument(..., help="What this key is for, e.g. staging"),
    workspace: WorkspaceOption = "",
    control_plane_url: str = "",
) -> None:
    """Create an API key. Shown once, never stored."""
    workspace_ref = resolve_workspace(workspace)
    with org_client(control_plane_url) as c:
        _key_created(payload(post_expecting(c, f"/v1/org/workspaces/{workspace_ref}/inference-keys", {"label": label}, ok=(200,))))


@workspaces_app.command("create")
def workspaces_create(
    name: str = typer.Argument(..., help="Workspace name, e.g. Staging"),
    slug: str = typer.Option("", "--slug", help="Short handle to use instead of the id; derived from the name when omitted"),
    control_plane_url: str = "",
) -> None:
    """Create a workspace. You become its first member."""
    with org_client(control_plane_url) as c:
        body = {"name": name, "slug": slug} if slug else {"name": name}
        created = payload(post_expecting(c, "/v1/org/workspaces", body, ok=(200,)))
    console.print(f"Created [bold]{created['slug']}[/bold]. Select it with airllm workspaces use {created['slug']}.")


register_create(
    providers_app,
    ProviderCreate,
    "/v1/taxonomy/providers",
    "Add an upstream provider for every organization on this instance.",
    lambda resp: console.print(f"Added [bold]{resp['name']}[/bold]. Add models, then airllm bundles compile."),
    client=instance_client,
    panel=ADMIN,
)
register_create(
    models_app,
    ModelCreate,
    "/v1/taxonomy/models",
    "Add a routable model for every organization on this instance.",
    lambda resp: console.print(f"Added [bold]{resp['name']}[/bold]. Run airllm bundles compile to apply."),
    client=instance_client,
    panel=ADMIN,
)


PROVIDER_CREDENTIAL_COLS = [
    Col("id", "ID", style="dim", no_wrap=True),
    Col("provider_name", "Provider"),
    Col("name", "Name", max_width=20),
    Col("scope", "Scope"),
    Col("priority", "Try", no_wrap=True),
    Col("health", "Health", style="yellow"),
    Col("fingerprint", "Key", style="cyan", fmt=lambda v: f"...{v}" if v else ""),
]


def _read_secret(prompt: str) -> str:
    """The key, from stdin when there is no terminal and a hidden prompt when there is.

    There is deliberately no --value flag: a key passed as an argument lands in the shell history
    and in the process list of every other user on the machine for as long as the command runs.
    Piping is the automated path, `echo $KEY | airllm provider-credentials add openai`.
    """
    if sys.stdin.isatty():
        return typer.prompt(prompt, hide_input=True)
    secret = sys.stdin.read().strip()
    if not secret:
        console.print("[red]No key on stdin. Pipe one in, or run this from a terminal.[/red]")
        raise typer.Exit(1)
    return secret


@provider_credentials_app.command("add")
def provider_credentials_add(  # noqa: PLR0913, PLR0917 flags are the command's interface
    provider: str = typer.Argument(..., help="Provider name, e.g. openai"),
    name: str = typer.Option("default", "--name", help="Name for this key, e.g. prod or backup"),
    workspace: WorkspaceOption = "",
    priority: int = typer.Option(100, "--priority", help="Lower is tried first"),
    org_wide: bool = typer.Option(False, "--org", help="Share across every workspace instead of one"),
    control_plane_url: str = "",
) -> None:
    """Add your own provider key. Read from stdin when piped, prompted for otherwise.

    Only the last four characters are kept for display.
    """
    secret = _read_secret(f"{provider} API key")
    body = {"provider": provider, "name": name, "value": secret, "priority": priority}
    if not org_wide:
        body["workspace"] = resolve_workspace(workspace)
    with org_client(control_plane_url) as c:
        credential = payload(post_expecting(c, "/v1/org/provider-credentials", body, ok=(200,)))
    scope = credential["scope"]
    console.print(f"Added [bold]{provider}[/bold] key [bold]{credential['name']}[/bold] to this {scope} (...{credential['fingerprint']})")
    console.print("[dim]Run airllm bundles compile to apply.[/dim]")


@provider_credentials_app.command("list")
def provider_credentials_list(
    workspace: WorkspaceOption = "",
    org_wide: bool = typer.Option(False, "--org", help="List every credential in the org rather than one workspace's"),
    control_plane_url: str = "",
    fmt: FormatOption = OutputFormat.table,
) -> None:
    """List provider keys, in the order they are tried."""
    params = {} if org_wide else {"workspace": resolve_workspace(workspace)}
    with org_client(control_plane_url) as c:
        resp = c.get("/v1/org/provider-credentials", params=params)
        ensure_ok(resp)
        rows = payload_rows(resp)
    print_rows("provider credentials", _credential_rows(rows), PROVIDER_CREDENTIAL_COLS, fmt)


@provider_credentials_app.command("rotate")
def provider_credentials_rotate(
    credential_id: str = typer.Argument(..., help="Credential id from `airllm provider-credentials list`"),
    control_plane_url: str = "",
) -> None:
    """Replace a provider key, keeping its name and position."""
    secret = _read_secret("replacement API key")
    with org_client(control_plane_url) as c:
        resp = c.put(f"/v1/org/provider-credentials/{credential_id}/value", json={"value": secret})
        ensure_ok(resp)
        credential = payload(resp)
    console.print(f"Rotated [bold]{credential['name']}[/bold] to ...{credential['fingerprint']}")
    console.print("[dim]Run airllm bundles compile to apply.[/dim]")


@provider_credentials_app.command("rm")
def provider_credentials_rm(
    credential_id: str = typer.Argument(..., help="Credential id from `airllm provider-credentials list`"),
    control_plane_url: str = "",
) -> None:
    """Delete a provider key."""
    with org_client(control_plane_url) as c:
        resp = c.delete(f"/v1/org/provider-credentials/{credential_id}")
        ensure_ok(resp)
    console.print(f"Deleted [bold]{credential_id}[/bold]. Run [bold]airllm bundles compile[/bold] to apply.")


@provider_credentials_app.command("disable")
def provider_credentials_disable(
    credential_id: str = typer.Argument(..., help="Credential id from `airllm provider-credentials list`"),
    enable: bool = typer.Option(False, "--enable", help="Put it back in the pool instead"),
    control_plane_url: str = "",
) -> None:
    """Stop using a provider key without deleting it. Use --enable to put it back."""
    with org_client(control_plane_url) as c:
        resp = c.patch(f"/v1/org/provider-credentials/{credential_id}", json={"enabled": enable})
        ensure_ok(resp)
        credential = payload(resp)
    state = "Enabled" if credential["enabled"] else "Disabled"
    console.print(f"{state} [bold]{credential['name']}[/bold]. Run [bold]airllm bundles compile[/bold] to apply.")
