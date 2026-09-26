from __future__ import annotations

import sys
import time
from collections import deque
from enum import StrEnum
from pathlib import Path  # noqa: TC003 Typer resolves command annotations at runtime
from typing import TYPE_CHECKING, Annotated
from uuid import UUID  # noqa: TC003 Typer resolves command annotations at runtime

import typer
import yaml
from dotenv import find_dotenv, load_dotenv
from rich.live import Live

from api_models import (
    DataPlaneInstanceOut,
    InferenceKeyCreatedOut,
    InferenceKeyOut,
    ManagementKeyCreatedOut,
    ManagementKeyOut,
    MeOut,
    OrgMemberOut,
    OrgOut,
    ProviderCredentialOut,
    TaxonomyApplyOut,
    TaxonomyChangeCounts,
    TaxonomyOut,
    UsageEventOut,
    UserOut,
    WorkspaceMembershipOut,
    WorkspaceOut,
)
from cli.client import (
    AllPagesOption,
    LimitOption,
    access_client,
    access_get,
    ensure_ok,
    org_path,
    payload,
    payload_page,
    post_expecting,
    resolve_org_id,
    resolve_workspace,
)
from cli.common import (
    catalog_app,
    console,
    events_app,
    gateways_app,
    inference_keys_app,
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
from cli.output import Col, FormatOption, OutputFormat, build_table, fmt_when, print_rows
from cli.profiles import active_profile, load_config, upsert_profile

if TYPE_CHECKING:
    import httpx
    from rich.table import Table

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
    Col("name", "Name", no_wrap=True),
    Col("kind", "Kind"),
    Col("base_url", "Base URL", max_width=45),
]
MODEL_COLS = [
    Col("name", "Name", no_wrap=True),
    Col("provider", "Provider"),
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


def _credential_rows(credentials: list[ProviderCredentialOut]) -> list[dict[str, object]]:
    """Fold enabled into health: a disabled key is out of the pool whatever its last request said,
    so that is the one fact worth a column."""
    return [
        {
            **credential.model_dump(mode="json"),
            "health": "disabled" if not credential.enabled else CREDENTIAL_HEALTH_LABELS.get(credential.status, credential.status),
        }
        for credential in credentials
    ]


def _money(value: object) -> str:
    return "" if value is None else str(value)


EVENT_COLS = [
    Col("occurred_at", "When", no_wrap=True, fmt=lambda v: str(v)[:19].replace("T", " ")),
    Col("request_id", "Request", style="dim", no_wrap=True, fmt=lambda v: str(v)[:8]),
    Col("workspace_id", "Workspace", style="dim", no_wrap=True, fmt=lambda v: str(v)[:8]),
    Col("model_id", "Model"),
    Col("status", "Status", style="yellow"),
    Col("input_tokens", "In"),
    Col("output_tokens", "Out"),
    Col("token_usage_source", "Token source"),
    Col("cache_read_tokens", "Cached", fmt=lambda v: str(v) if v else ""),
    Col("cost_input_usd", "$ in", fmt=_money),
    Col("cost_output_usd", "$ out", fmt=_money),
    Col("cost_usd", "$ total", fmt=_money),
    Col("latency_ms", "ms"),
    Col("stream", "Stream", fmt=lambda v: "yes" if v else ""),
]


@orgs_app.command("list")
def orgs_list(
    limit: LimitOption = 50, all_pages: AllPagesOption = False, control_plane_url: str = "", fmt: FormatOption = OutputFormat.table
) -> None:
    """List every organization on this instance."""
    print_rows("orgs", access_get("/api/v1/organizations", control_plane_url, OrgOut, limit=limit, all_pages=all_pages), ORG_COLS, fmt)


WorkspaceOption = Annotated[str, typer.Option("--workspace", "-w", help="Workspace name or id; defaults to your selected workspace")]


@workspaces_app.command("list")
def workspaces_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List your workspaces."""
    print_rows("workspaces", access_get(org_path("/workspaces"), control_plane_url, WorkspaceOut), WORKSPACE_COLS, fmt)


@workspaces_app.command("use")
def workspaces_use(workspace: str, control_plane_url: str = "") -> None:
    """Select the workspace that key commands use by default."""
    config = load_config()
    profile = active_profile(config)
    if profile is None or config.active is None:
        console.print("[red]Not signed in. Run [bold]airmux login[/bold].[/red]")
        raise typer.Exit(1)
    with access_client(control_plane_url) as c:
        resp = c.get(org_path(f"/workspaces/{workspace}"))
    if not resp.is_success:
        console.print(f"[red]No workspace [bold]{workspace}[/bold]. See [bold]airmux workspaces list[/bold].[/red]")
        raise typer.Exit(1)
    chosen = payload(resp, WorkspaceOut)
    updated_profile = profile.model_copy(update={"workspace": chosen.slug, "workspace_name": chosen.name})
    upsert_profile(config.active, updated_profile)
    console.print(f"Using workspace [bold]{chosen.slug}[/bold]")


@workspace_members_app.command("list")
def workspace_members_list(
    workspace: WorkspaceOption = "",
    control_plane_url: str = "",
    fmt: FormatOption = OutputFormat.table,
) -> None:
    """List who can use this workspace."""
    workspace_ref = resolve_workspace(workspace)
    rows = access_get(org_path(f"/workspaces/{workspace_ref}/members"), control_plane_url, WorkspaceMembershipOut)
    print_rows("members", rows, MEMBER_COLS, fmt)


@workspace_members_app.command("add")
def workspace_members_add(
    user_id: str,
    workspace: WorkspaceOption = "",
    role: str = typer.Option("member", "--role", help="Workspace role: admin, member, or viewer"),
    control_plane_url: str = "",
) -> None:
    """Give someone access to this workspace."""
    workspace_ref = resolve_workspace(workspace)
    with access_client(control_plane_url) as c:
        resp = c.put(org_path(f"/workspaces/{workspace_ref}/members/{user_id}"), json={"role": role})
        ensure_ok(resp)
    console.print(f"Added [bold]{user_id}[/bold] to [bold]{workspace_ref}[/bold]")


@workspace_members_app.command("remove")
def workspace_members_remove(user_id: str, workspace: WorkspaceOption = "", control_plane_url: str = "") -> None:
    """Remove a member from a workspace."""
    workspace_ref = resolve_workspace(workspace)
    with access_client(control_plane_url) as c:
        resp = c.delete(org_path(f"/workspaces/{workspace_ref}/members/{user_id}"))
        ensure_ok(resp)
    console.print(f"Removed [bold]{user_id}[/bold] from [bold]{workspace_ref}[/bold]")


@inference_keys_app.command("list")
def inference_keys_list(
    workspace: WorkspaceOption = "",
    control_plane_url: str = "",
    fmt: FormatOption = OutputFormat.table,
) -> None:
    """List this workspace's inference keys."""
    workspace_ref = resolve_workspace(workspace)
    print_rows(
        "inference keys",
        access_get(org_path(f"/workspaces/{workspace_ref}/inference-keys"), control_plane_url, InferenceKeyOut),
        KEY_COLS,
        fmt,
    )


@inference_keys_app.command("revoke")
def inference_keys_revoke(key_id: str, workspace: WorkspaceOption = "", control_plane_url: str = "") -> None:
    """Revoke an inference key."""
    workspace_ref = resolve_workspace(workspace)
    with access_client(control_plane_url) as c:
        resp = c.delete(org_path(f"/workspaces/{workspace_ref}/inference-keys/{key_id}"))
        ensure_ok(resp)
    console.print(f"Revoked [bold]{key_id}[/bold]")


def _permissions(value: object) -> str:
    return ", ".join(map(str, value)) if isinstance(value, list) else str(value or "")


MANAGEMENT_KEY_COLS = [
    Col("id", "ID", style="dim", no_wrap=True),
    Col("label", "Label", max_width=30),
    Col("scope", "Scope", fmt=lambda value: str(value.get("level", "")) if isinstance(value, dict) else str(value or "")),
    Col("org_id", "Org", no_wrap=True),
    Col("workspace_id", "Workspace", no_wrap=True),
    Col("user_id", "Principal", style="dim", no_wrap=True),
    Col("permissions", "Permissions", style="cyan", max_width=50, fmt=_permissions),
    Col("status", "Status", style="yellow"),
    Col("expires_at", "Expires", no_wrap=True, fmt=fmt_when),
    Col("created_at", "Created", no_wrap=True, fmt=fmt_when),
]

USER_COLS = [
    Col("id", "ID", style="dim", no_wrap=True),
    Col("email", "Email"),
    Col("name", "Name", max_width=30),
    Col("service_account", "Kind", fmt=lambda v: "service" if v else "human"),
    Col("instance_role", "Instance role", fmt=lambda v: str(v) if v else "none"),
    Col("orgs", "Orgs", style="cyan", max_width=40),
    Col("created_at", "Created", no_wrap=True, fmt=fmt_when),
]

ORG_MEMBER_COLS = [
    Col("user_id", "ID", style="dim", no_wrap=True),
    Col("email", "Email"),
    Col("name", "Name", max_width=30),
    Col("service_account", "Kind", fmt=lambda v: "service" if v else "human"),
    Col("role", "Role"),
    Col("status", "Status", style="yellow"),
]


@service_accounts_app.command("create")
def service_accounts_create(
    name: str | None = typer.Argument(None, help="Service account name; prompted for when omitted"),
    control_plane_url: str = "",
) -> None:
    """Create a machine account for CI or automation."""
    if not name:
        name = typer.prompt("name")
    with access_client(control_plane_url) as c:
        account = payload(post_expecting(c, "/api/v1/service-accounts", {"name": name}, ok=(200,)), UserOut)
    console.print(f"Created service account [bold]{account.email}[/bold]")
    console.print(f"[dim]Add it to your organization: airmux orgs members add {account.id}[/dim]")


@service_accounts_app.command("list")
def service_accounts_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List machine accounts."""
    rows = access_get("/api/v1/users", control_plane_url, UserOut, {"service_account": True})
    print_rows("service accounts", rows, USER_COLS, fmt)


@users_app.command("list")
def users_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List every account and the organizations it belongs to."""
    print_rows("users", access_get("/api/v1/users", control_plane_url, UserOut), USER_COLS, fmt)


class InstanceRoleOption(StrEnum):
    owner = "owner"
    auditor = "auditor"
    data_plane = "data_plane"
    none = "none"


@users_app.command("role")
def users_role(user_id: UUID, role: InstanceRoleOption, control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """Set an instance role, or use none to remove instance access."""
    with access_client(control_plane_url) as client:
        user = payload(
            ensure_ok(
                client.put(f"/api/v1/users/{user_id}/instance-role", json={"instance_role": None if role is InstanceRoleOption.none else role})
            ),
            UserOut,
        )
    print_rows("users", [user], USER_COLS, fmt)


@org_members_app.command("list")
def org_members_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List the active org's members."""
    print_rows("members", access_get(org_path("/users"), control_plane_url, OrgMemberOut), ORG_MEMBER_COLS, fmt)


@org_members_app.command("add")
def org_members_add(
    user_id: str,
    role: str = typer.Option("member", "--role", help="Organization role: owner, admin, member, or data_plane"),
    control_plane_url: str = "",
) -> None:
    """Add a principal to the active organization."""
    with access_client(control_plane_url) as c:
        resp = c.put(org_path(f"/users/{user_id}"), json={"role": role})
        ensure_ok(resp)
    console.print(f"Added [bold]{user_id}[/bold] to your organization")


@org_members_app.command("remove")
def org_members_remove(user_id: str, control_plane_url: str = "") -> None:
    """Remove a principal from the active organization."""
    with access_client(control_plane_url) as c:
        resp = c.delete(org_path(f"/users/{user_id}"))
        ensure_ok(resp)
    console.print(f"Removed [bold]{user_id}[/bold] from your organization")


@management_keys_app.command("list")
def management_keys_list(  # noqa: PLR0913, PLR0917 command flags define the CLI surface
    org_id: str = typer.Option("", "--org", help="Organization target; defaults to the active profile"),
    workspace_id: str = typer.Option("", "--workspace", help="Workspace target within the selected organization"),
    instance: bool = typer.Option(False, "--instance", help="List keys at instance scope"),
    user_id: str = typer.Option("", "--user", help="Only keys for this principal"),
    control_plane_url: str = "",
    fmt: FormatOption = OutputFormat.table,
) -> None:
    """List management keys at a tenancy scope."""
    if instance and (org_id or workspace_id):
        console.print("[red]--instance cannot be combined with --org or --workspace.[/red]")
        raise typer.Exit(1)
    selected_org = "" if instance else resolve_org_id(org_id)
    path = (
        "/api/v1/instance/management-keys"
        if instance
        else f"/api/v1/organizations/{selected_org}/workspaces/{workspace_id}/management-keys"
        if workspace_id
        else f"/api/v1/organizations/{selected_org}/management-keys"
    )
    print_rows(
        "management keys",
        access_get(path, control_plane_url, ManagementKeyOut, {"user_id": user_id} if user_id else None),
        MANAGEMENT_KEY_COLS,
        fmt,
    )


@management_keys_app.command("create")
def management_keys_create(  # noqa: PLR0913, PLR0917 command flags define the CLI surface
    label: str = typer.Option(..., "--label", help="What this key is for, e.g. ci"),
    permission: Annotated[list[str] | None, typer.Option("--permission", "-p", help="Permission ceiling; repeat for each permission")] = None,
    org_id: str = typer.Option("", "--org", help="Organization scope; defaults to the active profile"),
    workspace_id: str = typer.Option("", "--workspace", help="Workspace scope; requires an organization"),
    instance: bool = typer.Option(False, "--instance", help="Use instance scope instead of the active organization"),
    expires_at: str = typer.Option("", "--expires-at", help="Optional ISO 8601 expiration"),
    control_plane_url: str = "",
) -> None:
    """Create an explicitly limited management key. Shown once, never stored."""
    if not permission:
        console.print("[red]Pass at least one --permission.[/red]")
        raise typer.Exit(1)
    if instance and (org_id or workspace_id):
        console.print("[red]--instance cannot be combined with --org or --workspace.[/red]")
        raise typer.Exit(1)
    selected_org = "" if instance else resolve_org_id(org_id)
    path = (
        "/api/v1/instance/management-keys"
        if instance
        else f"/api/v1/organizations/{selected_org}/workspaces/{workspace_id}/management-keys"
        if workspace_id
        else f"/api/v1/organizations/{selected_org}/management-keys"
    )
    body = {
        "label": label,
        "permissions": permission,
        "expires_at": expires_at or None,
    }
    with access_client(control_plane_url) as c:
        key = payload(post_expecting(c, path, body, ok=(200,)), ManagementKeyCreatedOut)
    console.print(f"Management key [bold]{key.id}[/bold] created at [bold]{key.scope.level}[/bold] scope, shown once:")
    console.print(key.token)


@management_keys_app.command("revoke")
def management_keys_revoke(key_id: str, control_plane_url: str = "") -> None:
    """Revoke an management key and all keys delegated from it."""
    with access_client(control_plane_url) as c:
        resp = c.delete(f"/api/v1/management-keys/{key_id}")
        ensure_ok(resp)
    console.print(f"Revoked [bold]{key_id}[/bold]")


def _taxonomy(control_plane_url: str) -> TaxonomyOut:
    with access_client(control_plane_url) as c:
        resp = c.get(org_path("/taxonomy"))
        ensure_ok(resp)
        return payload(resp, TaxonomyOut)


@providers_app.command("list")
def providers_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List the providers you can route to."""
    print_rows("providers", _taxonomy(control_plane_url).providers, PROVIDER_COLS, fmt)


@models_app.command("list")
def models_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List the models you can route to, with pricing."""
    taxonomy = _taxonomy(control_plane_url)
    providers = {provider.id: provider.name for provider in taxonomy.providers}
    models = [{**model.model_dump(mode="json"), "provider": providers.get(model.provider_id, str(model.provider_id))} for model in taxonomy.models]
    print_rows("models", models, MODEL_COLS, fmt)


def _change_summary(changes: TaxonomyChangeCounts) -> str:
    return f"{changes.created} created, {changes.updated} updated, {changes.unchanged} unchanged"


@catalog_app.command("apply")
def catalog_apply(
    file: Annotated[Path, typer.Option("--file", exists=True, file_okay=True, dir_okay=False, readable=True, resolve_path=True)],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Validate and report changes without applying them")] = False,
    control_plane_url: str = "",
) -> None:
    """Apply a generated taxonomy to the instance catalog."""
    try:
        document = yaml.safe_load(file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        console.print(f"[red]Invalid taxonomy YAML: {error}[/red]")
        raise typer.Exit(1) from None
    if not isinstance(document, dict):
        console.print("[red]Invalid taxonomy YAML: expected a mapping with providers and models[/red]")
        raise typer.Exit(1)
    with access_client(control_plane_url) as client:
        response = client.post("/api/v1/instance/taxonomy", params={"dry_run": dry_run}, json=document, timeout=120.0)
        applied = payload(ensure_ok(response), TaxonomyApplyOut)
    action = "Dry run" if applied.dry_run else "Applied"
    console.print(f"{action}: providers {_change_summary(applied.providers)}; models {_change_summary(applied.models)}")


INSTANCE_COLS = [
    Col("instance_id", "Instance", style="dim", no_wrap=True, fmt=lambda v: str(v)[:12]),
    Col("status", "Status", style="yellow"),
    Col("version", "Version"),
    Col("bundle_id", "Bundle", style="dim", fmt=lambda v: str(v)[:8] if v else ""),
    Col("address", "Address"),
    Col("last_seen", "Last seen", no_wrap=True, fmt=fmt_when),
]


@gateways_app.command("list")
def gateways_list(
    all_: bool = typer.Option(False, "--all", help="Include gateways that are offline"),
    control_plane_url: str = "",
    fmt: FormatOption = OutputFormat.table,
) -> None:
    """List connected gateways."""
    load_dotenv(find_dotenv(usecwd=True))
    rows = access_get(
        "/api/v1/instance/data-planes",
        control_plane_url,
        DataPlaneInstanceOut,
        {"include_offline": all_},
    )
    print_rows("gateways", rows, INSTANCE_COLS, fmt)


@events_app.command("list")
def events_list(
    limit: LimitOption = 50, all_pages: AllPagesOption = False, control_plane_url: str = "", fmt: FormatOption = OutputFormat.table
) -> None:
    """List recent requests, newest first."""
    print_rows("events", access_get(org_path("/events"), control_plane_url, UsageEventOut, limit=limit, all_pages=all_pages), EVENT_COLS, fmt)


def _events_since(client: httpx.Client, path: str, newest_event_id: str | None) -> list[UsageEventOut]:
    cursor = None
    events = []
    while True:
        params = {"limit": 200, **({"cursor": cursor} if cursor else {})}
        page = payload_page(ensure_ok(client.get(path, params=params)), UsageEventOut)
        for event in page.items:
            if str(event.event_id) == newest_event_id:
                return list(reversed(events))
            events.append(event)
        if newest_event_id is None or page.next_cursor is None:
            return list(reversed(events))
        cursor = page.next_cursor


@events_app.command("tail")
def events_tail(interval: float = 2.0, keep: int = 30, control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """Follow requests as they happen."""
    rows: deque[UsageEventOut] = deque(maxlen=keep)
    fresh_ids: set[str] = set()

    def table() -> Table:
        return build_table(list(rows), EVENT_COLS, lambda values: "blink bold cyan" if values["event_id"] in fresh_ids else None)

    def emit(event: UsageEventOut) -> None:
        if fmt is OutputFormat.json:
            print(event.model_dump_json(), flush=True)
        else:
            values = event.model_dump(mode="json")
            print("\t".join(c.fmt(values.get(c.key)) for c in EVENT_COLS), flush=True)

    path = org_path("/events")
    with access_client(control_plane_url) as c:
        resp = c.get(path, params={"limit": keep})
        ensure_ok(resp)
        initial = payload_page(resp, UsageEventOut)
        rows.extend(reversed(initial.items))
        newest_event_id = str(initial.items[0].event_id) if initial.items else None
        try:
            if fmt is not OutputFormat.table:
                while True:
                    time.sleep(interval)
                    batch = _events_since(c, path, newest_event_id)
                    for event in batch:
                        emit(event)
                    if batch:
                        newest_event_id = str(batch[-1].event_id)
            with Live(table(), console=console, refresh_per_second=4) as live:
                while True:
                    time.sleep(interval)
                    batch = _events_since(c, path, newest_event_id)
                    fresh_ids = {str(event.event_id) for event in batch}
                    if batch:
                        rows.extend(batch)
                        newest_event_id = str(batch[-1].event_id)
                    live.update(table())
        except KeyboardInterrupt:
            console.print("[dim]stopped[/dim]")


def _key_created(key: InferenceKeyCreatedOut) -> None:
    console.print("Your new inference key, shown once:")
    console.print(key.token)


@orgs_app.command("create")
def orgs_create(
    name: str = typer.Argument(..., help="Organization name, e.g. My Org"),
    slug: str = typer.Option("", "--slug", help="Organization handle; derived from the name when omitted"),
    control_plane_url: str = "",
) -> None:
    """Create an organization."""
    body = {"name": name, "slug": slug}
    with access_client(control_plane_url) as client:
        organization = payload(post_expecting(client, "/api/v1/organizations", body, ok=(200,)), OrgOut)
    console.print(f"Created [bold]{organization.name}[/bold]. Add people with airmux orgs members add <user>.")


@inference_keys_app.command("create")
def inference_keys_create(
    label: str = typer.Argument(..., help="What this key is for, e.g. staging"),
    owner: str = typer.Option("", "--owner", help="Principal that this key represents; defaults to the current principal"),
    workspace: WorkspaceOption = "",
    control_plane_url: str = "",
) -> None:
    """Create an inference key. Shown once, never stored."""
    workspace_ref = resolve_workspace(workspace)
    with access_client(control_plane_url) as c:
        owner_id = owner or str(payload(ensure_ok(c.get("/api/v1/auth/me")), MeOut).user_id)
        _key_created(
            payload(
                post_expecting(
                    c,
                    org_path(f"/workspaces/{workspace_ref}/inference-keys"),
                    {"label": label, "user_id": owner_id},
                    ok=(200,),
                ),
                InferenceKeyCreatedOut,
            )
        )


@workspaces_app.command("create")
def workspaces_create(
    name: str = typer.Argument(..., help="Workspace name, e.g. Staging"),
    slug: str = typer.Option("", "--slug", help="Short handle to use instead of the id; derived from the name when omitted"),
    control_plane_url: str = "",
) -> None:
    """Create a workspace. You become its first member."""
    with access_client(control_plane_url) as c:
        body = {"name": name, "slug": slug} if slug else {"name": name}
        created = payload(post_expecting(c, org_path("/workspaces"), body, ok=(200,)), WorkspaceOut)
    console.print(f"Created [bold]{created.slug}[/bold]. Select it with airmux workspaces use {created.slug}.")


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
    Piping is the automated path, `echo $KEY | airmux provider-credentials add openai`.
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
    path = org_path("/provider-credentials" if org_wide else f"/workspaces/{resolve_workspace(workspace)}/provider-credentials")
    with access_client(control_plane_url) as c:
        credential = payload(post_expecting(c, path, body, ok=(200,)), ProviderCredentialOut)
    console.print(f"Added [bold]{provider}[/bold] key [bold]{credential.name}[/bold] to this {credential.scope} (...{credential.fingerprint})")


@provider_credentials_app.command("list")
def provider_credentials_list(
    workspace: WorkspaceOption = "",
    org_wide: bool = typer.Option(False, "--org", help="List every credential in the org rather than one workspace's"),
    control_plane_url: str = "",
    fmt: FormatOption = OutputFormat.table,
) -> None:
    """List provider keys, in the order they are tried."""
    path = org_path("/provider-credentials" if org_wide else f"/workspaces/{resolve_workspace(workspace)}/provider-credentials")
    rows = access_get(path, control_plane_url, ProviderCredentialOut)
    print_rows("provider credentials", _credential_rows(rows), PROVIDER_CREDENTIAL_COLS, fmt)


@provider_credentials_app.command("rotate")
def provider_credentials_rotate(
    credential_id: str = typer.Argument(..., help="Credential id from `airmux provider-credentials list`"),
    control_plane_url: str = "",
) -> None:
    """Replace a provider key, keeping its name and position."""
    secret = _read_secret("replacement API key")
    with access_client(control_plane_url) as c:
        resp = c.put(org_path(f"/provider-credentials/{credential_id}/value"), json={"value": secret})
        ensure_ok(resp)
    credential = payload(resp, ProviderCredentialOut)
    console.print(f"Rotated [bold]{credential.name}[/bold] to ...{credential.fingerprint}")


@provider_credentials_app.command("rm")
def provider_credentials_rm(
    credential_id: str = typer.Argument(..., help="Credential id from `airmux provider-credentials list`"),
    control_plane_url: str = "",
) -> None:
    """Delete a provider key."""
    with access_client(control_plane_url) as c:
        resp = c.delete(org_path(f"/provider-credentials/{credential_id}"))
        ensure_ok(resp)
    console.print(f"Deleted [bold]{credential_id}[/bold].")


@provider_credentials_app.command("disable")
def provider_credentials_disable(
    credential_id: str = typer.Argument(..., help="Credential id from `airmux provider-credentials list`"),
    enable: bool = typer.Option(False, "--enable", help="Put it back in the pool instead"),
    control_plane_url: str = "",
) -> None:
    """Stop using a provider key without deleting it. Use --enable to put it back."""
    with access_client(control_plane_url) as c:
        resp = c.patch(org_path(f"/provider-credentials/{credential_id}"), json={"enabled": enable})
        ensure_ok(resp)
        credential = payload(resp, ProviderCredentialOut)
    state = "Enabled" if credential.enabled else "Disabled"
    console.print(f"{state} [bold]{credential.name}[/bold].")
