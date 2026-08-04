from __future__ import annotations

from typing import TYPE_CHECKING

import typer
from dotenv import find_dotenv, load_dotenv

from cli.client import admin_client, admin_get, post_expecting
from cli.common import bundles_app, console, events_app, instances_app, keys_app, models_app, orgs_app, providers_app
from cli.forms import register_create
from cli.output import Col, FormatOption, OutputFormat, build_table, fmt_when, print_rows

if TYPE_CHECKING:
    from rich.table import Table
from cli.specs import KeyCreate, ModelCreate, OrgCreate, ProviderCreate

ORG_COLS = [
    Col("id", "ID", style="dim", no_wrap=True),
    Col("name", "Name", max_width=40),
    Col("created_at", "Created", no_wrap=True, fmt=fmt_when),
]
KEY_COLS = [
    Col("id", "ID", style="dim", no_wrap=True),
    Col("org_id", "Org"),
    Col("allowed_models", "Allowed models", style="cyan", max_width=40),
    Col("disabled", "Status", style="yellow", fmt=lambda v: "revoked" if v else "active"),
    Col("created_at", "Created", no_wrap=True, fmt=fmt_when),
]
PROVIDER_COLS = [
    Col("id", "ID", style="dim", no_wrap=True),
    Col("org_id", "Org"),
    Col("kind", "Kind"),
    Col("base_url", "Base URL", max_width=45),
    Col("credential_ref", "Credential", style="cyan", max_width=30),
]
MODEL_COLS = [
    Col("id", "ID", style="dim", no_wrap=True),
    Col("org_id", "Org"),
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
    """List orgs."""
    print_rows("orgs", admin_get("/admin/orgs", control_plane_url), ORG_COLS, fmt)


@keys_app.command("list")
def keys_list(org: str | None = None, control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List caller API keys with their status."""
    print_rows("keys", admin_get("/admin/keys", control_plane_url, org), KEY_COLS, fmt)


@keys_app.command("revoke")
def keys_revoke(key_id: str, control_plane_url: str = "") -> None:
    """Disable a key; lands in revocations at the next compile."""
    with admin_client(control_plane_url) as c:
        resp = c.delete(f"/admin/keys/{key_id}")
        resp.raise_for_status()
    console.print(f"key [bold]{key_id}[/bold] revoked, run `airllm bundles compile` to propagate")


@providers_app.command("list")
def providers_list(org: str | None = None, control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List upstream providers and their credential references."""
    print_rows("providers", admin_get("/admin/providers", control_plane_url, org), PROVIDER_COLS, fmt)


@models_app.command("list")
def models_list(org: str | None = None, control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List routable models with pricing and capabilities."""
    print_rows("models", admin_get("/admin/models", control_plane_url, org), MODEL_COLS, fmt)


@bundles_app.command("list")
def bundles_list(org: str | None = None, control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List compiled bundle versions and their validity windows."""
    print_rows("bundles", admin_get("/admin/bundles", control_plane_url, org), BUNDLE_COLS, fmt)


@bundles_app.command("compile")
def bundles_compile(org: str = "org-dev", control_plane_url: str = "") -> None:
    """Recompile and sign the bundle for an org."""
    with admin_client(control_plane_url) as c:
        compiled = post_expecting(c, "/admin/bundles/compile", {"org_id": org}, ok=(200,)).json()
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
    """List registered data planes; offline ones are shown only with --all."""
    load_dotenv(find_dotenv(usecwd=True))
    with admin_client(control_plane_url) as c:
        resp = c.get("/admin/instances", params={"include_offline": all_})
        resp.raise_for_status()
        print_rows("instances", resp.json(), INSTANCE_COLS, fmt)


@events_app.command("list")
def events_list(org: str | None = None, control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List the most recent usage events, newest first."""
    print_rows("events", admin_get("/admin/events", control_plane_url, org), EVENT_COLS, fmt)


@events_app.command("tail")
def events_tail(
    org: str | None = None, interval: float = 2.0, keep: int = 30, control_plane_url: str = "", fmt: FormatOption = OutputFormat.table
) -> None:
    """Follow usage events; a live table by default, one json or text line per event otherwise."""
    import json  # noqa: PLC0415 lazy import keeps CLI startup fast
    import time  # noqa: PLC0415 lazy import keeps CLI startup fast
    from collections import deque  # noqa: PLC0415 lazy import keeps CLI startup fast

    from rich.live import Live  # noqa: PLC0415 lazy import keeps CLI startup fast

    params: dict = {"org_id": org} if org else {}
    rows: deque[dict] = deque(maxlen=keep)
    fresh_ids: set[str] = set()

    def table() -> Table:
        return build_table(list(rows), EVENT_COLS, lambda r: "blink bold cyan" if r["event_id"] in fresh_ids else None)

    def emit(event: dict) -> None:
        if fmt is OutputFormat.json:
            print(json.dumps(event, ensure_ascii=False), flush=True)
        else:
            print("\t".join(c.fmt(event.get(c.key)) for c in EVENT_COLS), flush=True)

    with admin_client(control_plane_url) as c:
        resp = c.get("/admin/events", params={**params, "limit": keep})
        resp.raise_for_status()
        rows.extend(reversed(resp.json()))
        cursor = rows[-1]["occurred_at"] if rows else "1970-01-01T00:00:00"
        try:
            if fmt is not OutputFormat.table:
                while True:
                    time.sleep(interval)
                    resp = c.get("/admin/events", params={**params, "after": cursor, "limit": 200})
                    resp.raise_for_status()
                    for event in resp.json():
                        emit(event)
                        cursor = event["occurred_at"]
            with Live(table(), console=console, refresh_per_second=4) as live:
                while True:
                    time.sleep(interval)
                    resp = c.get("/admin/events", params={**params, "after": cursor, "limit": 200})
                    resp.raise_for_status()
                    batch = resp.json()
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
    "/admin/orgs",
    "Create an org; keys, providers and models hang off it.",
    lambda resp: console.print(f"org [bold]{resp['id']}[/bold] created"),
)
register_create(keys_app, KeyCreate, "/admin/keys", "Mint a key; the token is shown once and never stored.", _key_created)
register_create(
    providers_app,
    ProviderCreate,
    "/admin/providers",
    "Register an upstream provider.",
    lambda resp: console.print(f"provider [bold]{resp['provider_id']}[/bold] created, add models then `airllm bundles compile`"),
)
register_create(
    models_app,
    ModelCreate,
    "/admin/models",
    "Add a routable model.",
    lambda resp: console.print(f"model [bold]{resp['model_id']}[/bold] created, run `airllm bundles compile` to serve it"),
)
