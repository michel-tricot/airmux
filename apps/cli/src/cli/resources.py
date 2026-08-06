from __future__ import annotations

import json
import time
from collections import deque
from typing import TYPE_CHECKING

import typer
from dotenv import find_dotenv, load_dotenv
from rich.live import Live

from cli.client import instance_client, instance_get, org_client, org_get, payload, payload_rows, post_expecting
from cli.common import (
    bundles_app,
    console,
    events_app,
    instances_app,
    keys_app,
    models_app,
    orgs_app,
    providers_app,
    service_accounts_app,
    tokens_app,
    users_app,
)
from cli.forms import register_create
from cli.output import Col, FormatOption, OutputFormat, build_table, fmt_when, print_rows

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
    Col("org_id", "Org"),
    Col("user_id", "Owner", style="dim", no_wrap=True),
    Col("disabled", "Status", style="yellow", fmt=lambda v: "revoked" if v else "active"),
    Col("created_at", "Created", no_wrap=True, fmt=fmt_when),
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
    Col("org_id", "Org"),
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
    """List orgs; needs the instance token."""
    print_rows("orgs", instance_get("/v1/instance/orgs", control_plane_url), ORG_COLS, fmt)


@keys_app.command("list")
def keys_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List the org's inference keys with their status."""
    print_rows("keys", org_get("/v1/org/keys", control_plane_url), KEY_COLS, fmt)


@keys_app.command("revoke")
def keys_revoke(key_id: str, control_plane_url: str = "") -> None:
    """Disable a key; drops out of the bundle at the next compile."""
    with org_client(control_plane_url) as c:
        resp = c.delete(f"/v1/org/keys/{key_id}")
        resp.raise_for_status()
    console.print(f"key [bold]{key_id}[/bold] revoked, run `airllm bundles compile` to propagate")


TOKEN_COLS = [
    Col("id", "ID", style="dim", no_wrap=True),
    Col("org_id", "Scope", fmt=lambda v: str(v) if v else "instance"),
    Col("user_id", "Owner", style="dim", fmt=lambda v: str(v) if v else "system"),
    Col("revoked", "Status", style="yellow", fmt=lambda v: "revoked" if v else "active"),
    Col("created_at", "Created", no_wrap=True, fmt=fmt_when),
]

USER_COLS = [
    Col("id", "ID", style="dim", no_wrap=True),
    Col("email", "Email"),
    Col("name", "Name", max_width=30),
    Col("service_account", "Kind", fmt=lambda v: "service" if v else "human"),
    Col("instance_admin", "Role", style="yellow", fmt=lambda v: "instance admin" if v else "member"),
    Col("orgs", "Orgs", style="cyan", max_width=40),
    Col("created_at", "Created", no_wrap=True, fmt=fmt_when),
]


@users_app.command("create")
def users_create(
    email: str,
    name: str = "",
    admin: bool = typer.Option(False, "--admin", help="Make the user an instance admin"),
    control_plane_url: str = "",
) -> None:
    """Create a user; add org memberships with `airllm users join`. Needs the instance token."""
    body = {"email": email, "name": name, "instance_admin": admin}
    with instance_client(control_plane_url) as c:
        resp = payload(post_expecting(c, "/v1/instance/users", body, ok=(200,)))
    role = "instance admin" if resp["instance_admin"] else "member"
    console.print(f"user [bold]{resp['id']}[/bold] created for {resp['email']} as {role}")


@service_accounts_app.command("create")
def service_accounts_create(
    name: str | None = typer.Argument(None, help="Service account name; prompted for when omitted"),
    admin: bool = typer.Option(False, "--admin", help="Make the service account an instance admin"),
    control_plane_url: str = "",
) -> None:
    """Create a service account; its email is derived as name-<id>@airbytesvcaccount.ai. Needs the instance token."""
    if not name:
        name = typer.prompt("name")
    with instance_client(control_plane_url) as c:
        resp = payload(post_expecting(c, "/v1/instance/service-accounts", {"name": name, "instance_admin": admin}, ok=(200,)))
    console.print(f"service account [bold]{resp['id']}[/bold] created as {resp['email']}")
    console.print(
        f"[dim]add it to an org with `airllm users join {resp['id']} <org>`, "
        f"then mint its token with `airllm tokens mint <org> --user {resp['id']}`[/dim]"
    )


@service_accounts_app.command("list")
def service_accounts_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List service accounts; needs the instance token."""
    rows = [u for u in instance_get("/v1/instance/users", control_plane_url) if u["service_account"]]
    print_rows("service accounts", rows, USER_COLS, fmt)


@users_app.command("list")
def users_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List users with their org memberships; needs the instance token."""
    print_rows("users", instance_get("/v1/instance/users", control_plane_url), USER_COLS, fmt)


@users_app.command("join")
def users_join(user_id: str, org: str, control_plane_url: str = "") -> None:
    """Add a user to an org; their org tokens start working immediately."""
    with instance_client(control_plane_url) as c:
        resp = c.put(f"/v1/instance/users/{user_id}/orgs/{org}")
        resp.raise_for_status()
    console.print(f"user [bold]{user_id}[/bold] is now a member of [bold]{org}[/bold]")


@users_app.command("leave")
def users_leave(user_id: str, org: str, control_plane_url: str = "") -> None:
    """Remove a user from an org; their tokens for that org stop working immediately."""
    with instance_client(control_plane_url) as c:
        resp = c.delete(f"/v1/instance/users/{user_id}/orgs/{org}")
        resp.raise_for_status()
    console.print(f"user [bold]{user_id}[/bold] removed from [bold]{org}[/bold]")


@tokens_app.command("list")
def tokens_list(org: str | None = None, control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List management tokens minted through the API; needs the instance token."""
    print_rows("tokens", instance_get("/v1/instance/tokens", control_plane_url, {"org_id": org} if org else None), TOKEN_COLS, fmt)


@tokens_app.command("mint")
def tokens_mint(
    org: str | None = typer.Argument(None, help="Org to scope the token to; omit for an instance token"),
    user: str = typer.Option(..., "--user", help="User the token is minted for; the scope must be backed by their memberships"),
    control_plane_url: str = "",
) -> None:
    """Mint a management token; the token is shown once and never stored."""
    with instance_client(control_plane_url) as c:
        resp = payload(post_expecting(c, f"/v1/instance/users/{user}/tokens", {"org_id": org}, ok=(200,)))
    scope = resp["org_id"] or "instance"
    console.print(
        f"management token [bold]{resp['token_id']}[/bold] minted for [bold]{scope}[/bold] "
        f"for user [bold]{resp['user_id']}[/bold], token (shown once):"
    )
    console.print(resp["token"])


@tokens_app.command("revoke")
def tokens_revoke(token_id: str, control_plane_url: str = "") -> None:
    """Revoke a management token; takes effect on the next request."""
    with instance_client(control_plane_url) as c:
        resp = c.delete(f"/v1/instance/tokens/{token_id}")
        resp.raise_for_status()
    console.print(f"management token [bold]{token_id}[/bold] revoked")


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
    console.print(f"bundle [bold]{compiled['bundle_id']}[/bold] v{compiled['version']} compiled")


INSTANCE_COLS = [
    Col("instance_id", "Instance", style="dim", no_wrap=True, fmt=lambda v: str(v)[:12]),
    Col("org_id", "Org"),
    Col("status", "Status", style="yellow"),
    Col("version", "Version"),
    Col("bundle_id", "Bundle", style="dim", fmt=lambda v: str(v)[:8] if v else ""),
    Col("address", "Address"),
    Col("last_seen", "Last seen", no_wrap=True, fmt=fmt_when),
]


@instances_app.command("list")
def instances_list(
    all_: bool = typer.Option(False, "--all", help="Include offline instances (kept as history)"),
    control_plane_url: str = "",
    fmt: FormatOption = OutputFormat.table,
) -> None:
    """List the org's data planes; offline ones are shown only with --all."""
    load_dotenv(find_dotenv(usecwd=True))
    with org_client(control_plane_url) as c:
        resp = c.get("/v1/org/instances", params={"include_offline": all_})
        resp.raise_for_status()
        print_rows("instances", payload_rows(resp), INSTANCE_COLS, fmt)


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
    console.print(f"key [bold]{resp['key_id']}[/bold] minted, token (shown once):")
    console.print(resp["token"])
    console.print("[dim]run `airllm bundles compile` to include it in the next bundle[/dim]")


register_create(
    orgs_app,
    OrgCreate,
    "/v1/instance/orgs",
    "Create an org; keys and bundles hang off it. Needs the instance token.",
    lambda resp: console.print(f"org [bold]{resp['id']}[/bold] created, mint its admin token with `airllm tokens mint {resp['id']}`"),
    client=instance_client,
)


@keys_app.command("create")
def keys_create(control_plane_url: str = "") -> None:
    """Mint a key; the token is shown once and never stored."""
    with org_client(control_plane_url) as c:
        _key_created(payload(post_expecting(c, "/v1/org/keys", None, ok=(200,))))


register_create(
    providers_app,
    ProviderCreate,
    "/v1/taxonomy/providers",
    "Register an upstream provider for the whole instance. Needs the instance token.",
    lambda resp: console.print(f"provider [bold]{resp['id']}[/bold] created, add models then `airllm bundles compile`"),
    client=instance_client,
)
register_create(
    models_app,
    ModelCreate,
    "/v1/taxonomy/models",
    "Add a routable model for the whole instance. Needs the instance token.",
    lambda resp: console.print(f"model [bold]{resp['id']}[/bold] created, run `airllm bundles compile` to serve it"),
    client=instance_client,
)
