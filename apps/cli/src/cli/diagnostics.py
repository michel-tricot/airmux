from __future__ import annotations

import os
import stat
from typing import TYPE_CHECKING

import httpx
import typer

from cli.client import resolve_control_plane_url
from cli.common import SETUP, app, console, profiles_app
from cli.output import Col, FormatOption, OutputFormat, print_rows
from cli.profiles import active_profile, config_path, load_config, remove_profile, set_active

if TYPE_CHECKING:
    from collections.abc import Callable


PROFILE_COLS = [
    Col("active", "Active", fmt=lambda value: "*" if value else ""),
    Col("name", "Profile", no_wrap=True),
    Col("scope", "Scope"),
    Col("organization", "Organization"),
    Col("workspace", "Workspace"),
    Col("control_plane_url", "Control plane"),
    Col("gateway_url", "Gateway"),
]
STATUS_COLS = [
    Col("profile", "Profile"),
    Col("control_plane", "Control plane"),
    Col("gateway", "Gateway"),
    Col("organization", "Organization"),
    Col("workspace", "Workspace"),
    Col("authentication", "Authentication"),
]
DIAGNOSTIC_COLS = [
    Col("check", "Check", no_wrap=True),
    Col("status", "Status", no_wrap=True),
    Col("detail", "Detail"),
]
PRIVATE_FILE_MODE = 0o600


def _profile_rows() -> list[dict]:
    config = load_config()
    active = config.get("active")
    profiles = config.get("profiles") or {}
    return [
        {
            "active": name == active,
            "name": name,
            "scope": profile.get("scope") or ("org" if profile.get("org_id") else "instance"),
            "organization": profile.get("org_name", ""),
            "workspace": profile.get("workspace_name") or profile.get("workspace", ""),
            "control_plane_url": profile.get("control_plane_url", ""),
            "gateway_url": profile.get("gateway_url", ""),
        }
        for name, profile in profiles.items()
    ]


def resolve_gateway_url(override: str = "") -> str:
    profile = active_profile() or {}
    return override or os.environ.get("GW_GATEWAY_URL") or str(profile.get("gateway_url") or "http://localhost:8080")


@profiles_app.command("list")
def profiles_list(fmt: FormatOption = OutputFormat.table) -> None:
    """List saved contexts without exposing their access keys."""
    print_rows("profiles", _profile_rows(), PROFILE_COLS, fmt)


@profiles_app.command("use")
def profiles_use(name: str) -> None:
    """Select the context used by commands without explicit scope flags."""
    try:
        set_active(name)
    except KeyError:
        console.print(f"[red]No profile [bold]{name}[/bold]. See [bold]airllm profiles list[/bold].[/red]")
        raise typer.Exit(1) from None
    console.print(f"Using profile [bold]{name}[/bold]")


@profiles_app.command("remove")
def profiles_remove(name: str) -> None:
    """Remove a saved context and its access key from this machine."""
    try:
        remove_profile(name)
    except KeyError:
        console.print(f"[red]No profile [bold]{name}[/bold]. See [bold]airllm profiles list[/bold].[/red]")
        raise typer.Exit(1) from None
    console.print(f"Removed profile [bold]{name}[/bold]")


@app.command(rich_help_panel=SETUP)
def status(fmt: FormatOption = OutputFormat.table) -> None:
    """Show the context and endpoints the next command will use."""
    profile = active_profile() or {}
    rows = [
        {
            "profile": profile.get("name", "none"),
            "control_plane": resolve_control_plane_url(),
            "gateway": resolve_gateway_url(),
            "organization": os.environ.get("GW_ORG_ID") or profile.get("org_name", ""),
            "workspace": profile.get("workspace_name") or profile.get("workspace", ""),
            "authentication": "environment" if os.environ.get("GW_ACCESS_KEY") else "profile" if profile.get("token") else "none",
        }
    ]
    print_rows("status", rows, STATUS_COLS, fmt)


def _request_check(name: str, request: Callable[[], httpx.Response]) -> dict:
    try:
        response = request()
    except httpx.HTTPError as error:
        return {"check": name, "status": "failed", "detail": str(error)}
    if response.is_success:
        return {"check": name, "status": "ok", "detail": f"HTTP {response.status_code}"}
    try:
        body = response.json()
        detail = str(body.get("detail") or body.get("status") or response.text)
    except (ValueError, AttributeError):
        detail = response.text or response.reason_phrase
    return {"check": name, "status": "failed", "detail": f"HTTP {response.status_code}: {detail}"}


def diagnostic_rows(control_plane_url: str, gateway_url: str) -> list[dict]:
    profile = active_profile() or {}
    token = os.environ.get("GW_ACCESS_KEY") or profile.get("token")
    path = config_path()
    if path.exists():
        private = stat.S_IMODE(path.stat().st_mode) == PRIVATE_FILE_MODE
        config_check = {"check": "CLI config", "status": "ok" if private else "failed", "detail": str(path)}
    elif token:
        config_check = {"check": "CLI config", "status": "ok", "detail": "using environment credentials"}
    else:
        config_check = {"check": "CLI config", "status": "failed", "detail": "no saved profile"}
    headers = {"authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(timeout=5.0) as client:
        return [
            config_check,
            _request_check("Control plane", lambda: client.get(f"{control_plane_url.rstrip('/')}/healthz")),
            _request_check("Authentication", lambda: client.get(f"{control_plane_url.rstrip('/')}/api/v1/auth/me", headers=headers)),
            _request_check("Gateway", lambda: client.get(f"{gateway_url.rstrip('/')}/readyz")),
        ]


@app.command(rich_help_panel=SETUP)
def doctor(
    control_plane_url: str = typer.Option("", help="Control plane URL; defaults to the active context"),
    gateway_url: str = typer.Option("", help="Gateway URL; defaults to GW_GATEWAY_URL or the active context"),
    fmt: FormatOption = OutputFormat.table,
) -> None:
    """Check local credentials, control-plane access, and gateway readiness."""
    control_plane = resolve_control_plane_url(control_plane_url)
    gateway = resolve_gateway_url(gateway_url)
    rows = diagnostic_rows(control_plane, gateway)
    print_rows("diagnostics", rows, DIAGNOSTIC_COLS, fmt)
    if any(row["status"] == "failed" for row in rows):
        raise typer.Exit(1)
