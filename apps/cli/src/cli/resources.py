from __future__ import annotations

import json
import time
from collections import deque
from typing import TYPE_CHECKING, Annotated

import typer
from dotenv import find_dotenv, load_dotenv
from rich.live import Live

from cli.client import instance_client, instance_get, org_client, org_get, payload, payload_rows, post_expecting, resolve_workspace
from cli.common import (
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
    Col("credential_ref", "Credential", style="cyan", max_width=30),
]
MODEL_COLS = [
    Col("id", "ID", style="dim", no_wrap=True),
    Col("provider_id", "Provider"),
    Col("upstream_model", "Upstream model"),
    Col("input_price_per_mtok", "$/Mtok in"),
    Col("output_price_per_mtok", "$/Mtok out"),
    Col("context_window", "Context"),
    Col("max_output_tokens", "Max out"),
    Col("capabilities", "Capabilities", style="cyan", max_width=30),
]


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


@orgs_app.command("list")
def orgs_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List orgs; needs the instance management key."""
    print_rows("orgs", instance_get("/v1/orgs", control_plane_url), ORG_COLS, fmt)


WorkspaceOption = Annotated[str, typer.Option("--workspace", "-w", help="Workspace name or id; defaults to the profile's workspace")]


@workspaces_app.command("list")
def workspaces_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List the org's workspaces."""
    print_rows("workspaces", org_get("/v1/org/workspaces", control_plane_url), WORKSPACE_COLS, fmt)


@workspaces_app.command("use")
def workspaces_use(workspace: str, control_plane_url: str = "") -> None:
    """Make a workspace the default for key commands, stored in the active profile."""
    profile = active_profile()
    if profile is None:
        console.print("[red]no active profile: run `airllm login` first[/red]")
        raise typer.Exit(1)
    workspace_id = resolve_workspace(workspace, control_plane_url)
    name = str(profile.pop("name"))
    upsert_profile(name, {**profile, "workspace_id": workspace_id, "workspace_name": workspace})
    console.print(f"workspace [bold]{workspace}[/bold] is now the default for [bold]{name}[/bold]")


@workspace_members_app.command("list")
def workspace_members_list(workspace: WorkspaceOption = "", control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List a workspace's members."""
    workspace_id = resolve_workspace(workspace, control_plane_url)
    print_rows("members", org_get(f"/v1/org/workspaces/{workspace_id}/members", control_plane_url), MEMBER_COLS, fmt)


@workspace_members_app.command("add")
def workspace_members_add(user_id: str, workspace: WorkspaceOption = "", control_plane_url: str = "") -> None:
    """Add an org member to a workspace; key operations there start working immediately."""
    workspace_id = resolve_workspace(workspace, control_plane_url)
    with org_client(control_plane_url) as c:
        resp = c.put(f"/v1/org/workspaces/{workspace_id}/members/{user_id}")
        resp.raise_for_status()
    console.print(f"user [bold]{user_id}[/bold] is now a member of workspace [bold]{workspace_id}[/bold]")


@workspace_members_app.command("remove")
def workspace_members_remove(user_id: str, workspace: WorkspaceOption = "", control_plane_url: str = "") -> None:
    """Remove a member from a workspace; their keys there keep working until revoked."""
    workspace_id = resolve_workspace(workspace, control_plane_url)
    with org_client(control_plane_url) as c:
        resp = c.delete(f"/v1/org/workspaces/{workspace_id}/members/{user_id}")
        resp.raise_for_status()
    console.print(f"user [bold]{user_id}[/bold] removed from workspace [bold]{workspace_id}[/bold]")


@inference_keys_app.command("list")
def inference_keys_list(workspace: WorkspaceOption = "", control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List the workspace's inference keys with their status."""
    workspace_id = resolve_workspace(workspace, control_plane_url)
    print_rows("inference keys", org_get(f"/v1/org/workspaces/{workspace_id}/inference-keys", control_plane_url), KEY_COLS, fmt)


@inference_keys_app.command("revoke")
def inference_keys_revoke(key_id: str, workspace: WorkspaceOption = "", control_plane_url: str = "") -> None:
    """Disable a key; drops out of the bundle at the next compile."""
    workspace_id = resolve_workspace(workspace, control_plane_url)
    with org_client(control_plane_url) as c:
        resp = c.delete(f"/v1/org/workspaces/{workspace_id}/inference-keys/{key_id}")
        resp.raise_for_status()
    console.print(f"key [bold]{key_id}[/bold] revoked, run `airllm bundles compile` to propagate")


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
    """Create a user; add org memberships with `airllm orgs members add`. Needs the instance key."""
    body = {"email": email, "name": name}
    with instance_client(control_plane_url) as c:
        resp = payload(post_expecting(c, "/v1/users", body, ok=(200,)))
    console.print(f"user [bold]{resp['id']}[/bold] created for {resp['email']}")


@service_accounts_app.command("create")
def service_accounts_create(
    name: str | None = typer.Argument(None, help="Service account name; prompted for when omitted"),
    control_plane_url: str = "",
) -> None:
    """Create a service account; its email is derived as name-<id>@airbytesvcaccount.ai. Needs the instance management key."""
    if not name:
        name = typer.prompt("name")
    with instance_client(control_plane_url) as c:
        resp = payload(post_expecting(c, "/v1/service-accounts", {"name": name}, ok=(200,)))
    console.print(f"service account [bold]{resp['id']}[/bold] created as {resp['email']}")
    console.print(f"[dim]add it to your active org with `airllm orgs members add {resp['id']}`[/dim]")


@service_accounts_app.command("list")
def service_accounts_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List service accounts; needs the instance management key."""
    rows = [u for u in instance_get("/v1/users", control_plane_url) if u["service_account"]]
    print_rows("service accounts", rows, USER_COLS, fmt)


@users_app.command("list")
def users_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List users with their org memberships; needs the instance management key."""
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
        resp.raise_for_status()
    console.print(f"user [bold]{user_id}[/bold] is now a member of the active org")


@org_members_app.command("remove")
def org_members_remove(user_id: str, control_plane_url: str = "") -> None:
    """Remove a user from the active org; their management keys for it stop working immediately."""
    with org_client(control_plane_url) as c:
        resp = c.delete(f"/v1/org/users/{user_id}")
        resp.raise_for_status()
    console.print(f"user [bold]{user_id}[/bold] removed from the active org")


@management_keys_app.command("list")
def management_keys_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List the org's management keys."""
    print_rows("management keys", org_get("/v1/org/management-keys", control_plane_url), MANAGEMENT_KEY_COLS, fmt)


@management_keys_app.command("mint")
def management_keys_mint(
    label: str = typer.Option(..., "--label", help="Where the key will live, e.g. ci; shown in listings"),
    user: str = typer.Option("", "--user", help="Org member the key is minted for; defaults to you"),
    scope: Annotated[
        list[str] | None, typer.Option("--scope", help="Restrict the key to a scope, repeatable (e.g. inference-keys:read); omit for full authority")
    ] = None,
    control_plane_url: str = "",
) -> None:
    """Mint a management key in the active org; the secret is shown once and never stored."""
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
    """Revoke one of the org's management keys; takes effect on the next request."""
    with org_client(control_plane_url) as c:
        resp = c.delete(f"/v1/org/management-keys/{key_id}")
        resp.raise_for_status()
    console.print(f"management key [bold]{key_id}[/bold] revoked")


@instance_keys_app.command("list")
def instance_keys_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List the instance keys; there is no org axis to filter on."""
    print_rows("instance keys", instance_get("/v1/instance/instance-keys", control_plane_url), INSTANCE_KEY_COLS, fmt)


@instance_keys_app.command("mint")
def instance_keys_mint(
    label: str = typer.Option(..., "--label", help="Where the key will live, e.g. ci or a data plane; shown in listings"),
    user: str = typer.Option("", "--user", help="Instance admin the key is minted for; defaults to you"),
    scope: Annotated[
        list[str] | None, typer.Option("--scope", help="Restrict the key to a scope, repeatable (e.g. sync); omit for full authority")
    ] = None,
    control_plane_url: str = "",
) -> None:
    """Mint an instance key; the secret is shown once and never stored."""
    body = {"user_id": user or None, "scopes": scope or None, "label": label}
    with instance_client(control_plane_url) as c:
        resp = payload(post_expecting(c, "/v1/instance/instance-keys", body, ok=(200,)))
    restriction = f" restricted to {', '.join(resp['scopes'])}" if resp.get("scopes") else ""
    console.print(f"instance key [bold]{resp['id']}[/bold] minted for user [bold]{resp['user_id']}[/bold]{restriction}, secret (shown once):")
    console.print(resp["token"])


@instance_keys_app.command("revoke")
def instance_keys_revoke(key_id: str, control_plane_url: str = "") -> None:
    """Revoke an instance key; takes effect on the next request."""
    with instance_client(control_plane_url) as c:
        resp = c.delete(f"/v1/instance/instance-keys/{key_id}")
        resp.raise_for_status()
    console.print(f"instance key [bold]{key_id}[/bold] revoked")


def _taxonomy(control_plane_url: str) -> dict:
    with org_client(control_plane_url) as c:
        resp = c.get("/v1/taxonomy")
        resp.raise_for_status()
        return payload(resp)


@providers_app.command("list")
def providers_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List the instance's upstream providers and their credential references."""
    print_rows("providers", _taxonomy(control_plane_url)["providers"], PROVIDER_COLS, fmt)


@models_app.command("list")
def models_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List the instance's routable models with pricing and capabilities."""
    print_rows("models", _taxonomy(control_plane_url)["models"], MODEL_COLS, fmt)


@bundles_app.command("list")
def bundles_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List the org's compiled bundle versions and their validity windows."""
    print_rows("bundles", org_get("/v1/org/bundles", control_plane_url), BUNDLE_COLS, fmt)


@bundles_app.command("compile")
def bundles_compile(control_plane_url: str = "") -> None:
    """Recompile and sign the org's bundle."""
    with org_client(control_plane_url) as c:
        compiled = payload(post_expecting(c, "/v1/org/bundles/compile", {}, ok=(200,)))
    console.print(f"bundle [bold]{compiled['id']}[/bold] v{compiled['version']} compiled")


INSTANCE_COLS = [
    Col("instance_id", "Instance", style="dim", no_wrap=True, fmt=lambda v: str(v)[:12]),
    Col("org_id", "Org"),
    Col("status", "Status", style="yellow"),
    Col("version", "Version"),
    Col("bundle_id", "Bundle", style="dim", fmt=lambda v: str(v)[:8] if v else ""),
    Col("address", "Address"),
    Col("last_seen", "Last seen", no_wrap=True, fmt=fmt_when),
]


@data_planes_app.command("list")
def data_planes_list(
    all_: bool = typer.Option(False, "--all", help="Include offline data planes (kept as history)"),
    control_plane_url: str = "",
    fmt: FormatOption = OutputFormat.table,
) -> None:
    """List the instance's data planes; offline ones are shown only with --all. Needs the instance management key."""
    load_dotenv(find_dotenv(usecwd=True))
    with instance_client(control_plane_url) as c:
        resp = c.get("/v1/instance/data-planes", params={"include_offline": all_})
        resp.raise_for_status()
        print_rows("data planes", payload_rows(resp), INSTANCE_COLS, fmt)


@events_app.command("list")
def events_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List the org's most recent usage events, newest first."""
    print_rows("events", org_get("/v1/org/events", control_plane_url), EVENT_COLS, fmt)


@events_app.command("tail")
def events_tail(interval: float = 2.0, keep: int = 30, control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """Follow the org's usage events; a live table by default, one json or text line per event otherwise."""
    params: dict = {}
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
        resp = c.get("/v1/org/events", params={**params, "limit": keep})
        resp.raise_for_status()
        rows.extend(reversed(payload_rows(resp)))
        cursor = rows[-1]["occurred_at"] if rows else "1970-01-01T00:00:00"
        try:
            if fmt is not OutputFormat.table:
                while True:
                    time.sleep(interval)
                    resp = c.get("/v1/org/events", params={**params, "after": cursor, "limit": 200})
                    resp.raise_for_status()
                    for event in payload_rows(resp):
                        emit(event)
                        cursor = event["occurred_at"]
            with Live(table(), console=console, refresh_per_second=4) as live:
                while True:
                    time.sleep(interval)
                    resp = c.get("/v1/org/events", params={**params, "after": cursor, "limit": 200})
                    resp.raise_for_status()
                    batch = payload_rows(resp)
                    fresh_ids = {event["event_id"] for event in batch}
                    if batch:
                        rows.extend(batch)
                        cursor = batch[-1]["occurred_at"]
                    live.update(table())
        except KeyboardInterrupt:
            console.print("[dim]stopped[/dim]")


def _key_created(resp: dict) -> None:
    console.print(f"key [bold]{resp['id']}[/bold] minted, token (shown once):")
    console.print(resp["token"])
    console.print("[dim]run `airllm bundles compile` to include it in the next bundle[/dim]")


register_create(
    orgs_app,
    OrgCreate,
    "/v1/orgs",
    "Create an org; keys and bundles hang off it. Needs the instance management key.",
    lambda resp: console.print(f"org [bold]{resp['id']}[/bold] created, add members with `airllm orgs members add <user>` in its scope"),
    client=instance_client,
)


@inference_keys_app.command("create")
def inference_keys_create(
    label: str = typer.Argument(..., help="What the key is for, e.g. staging; shown in listings"),
    workspace: WorkspaceOption = "",
    control_plane_url: str = "",
) -> None:
    """Mint an inference key in a workspace; the token is shown once and never stored."""
    workspace_id = resolve_workspace(workspace, control_plane_url)
    with org_client(control_plane_url) as c:
        _key_created(payload(post_expecting(c, f"/v1/org/workspaces/{workspace_id}/inference-keys", {"label": label}, ok=(200,))))


@workspaces_app.command("create")
def workspaces_create(
    name: str = typer.Argument(..., help="Workspace name, e.g. staging"),
    control_plane_url: str = "",
) -> None:
    """Create a workspace in the active org; you become its first member."""
    with org_client(control_plane_url) as c:
        created = payload(post_expecting(c, "/v1/org/workspaces", {"name": name}, ok=(200,)))
    console.print(f"workspace [bold]{created['id']}[/bold] created, run `airllm workspaces use {created['name']}` to make it the default")


register_create(
    providers_app,
    ProviderCreate,
    "/v1/taxonomy/providers",
    "Register an upstream provider for the whole instance. Needs the instance management key.",
    lambda resp: console.print(f"provider [bold]{resp['id']}[/bold] created, add models then `airllm bundles compile`"),
    client=instance_client,
)
register_create(
    models_app,
    ModelCreate,
    "/v1/taxonomy/models",
    "Add a routable model for the whole instance. Needs the instance management key.",
    lambda resp: console.print(f"model [bold]{resp['id']}[/bold] created, run `airllm bundles compile` to serve it"),
    client=instance_client,
)
