from __future__ import annotations

import os
from typing import TYPE_CHECKING

import typer

from cli.common import console, invocation
from cli.profiles import active_profile, admin_keys_url

if TYPE_CHECKING:
    import httpx


LOCAL_CONTROL_PLANE_URL = "http://127.0.0.1:8000"


def resolve_control_plane_url(override: str = "") -> str:
    """The control plane this run talks to.

    An explicit flag always wins, then --dev, then the environment, then the profile the last login
    wrote. --dev sits above the environment and the profile so a stale login cannot redirect a
    development run.

    airllm.yml is deliberately not consulted. It configures the two servers, which read it from
    their own working directory; a CLI run from anywhere else would either miss it or pick up a
    checkout that has nothing to do with the deployment the user is signed into.
    """
    if override:
        return override
    if invocation.dev:
        return LOCAL_CONTROL_PLANE_URL
    if url := os.environ.get("GW_CONTROL_PLANE_URL"):
        return url
    profile = active_profile()
    if profile and profile.get("control_plane_url"):
        return str(profile["control_plane_url"])
    return LOCAL_CONTROL_PLANE_URL


def _bearer_client(token: str, control_plane_url: str) -> httpx.Client:
    import httpx  # noqa: PLC0415 lazy import keeps CLI startup fast

    return httpx.Client(base_url=resolve_control_plane_url(control_plane_url), headers={"authorization": f"Bearer {token}"}, timeout=10.0)


def instance_client(control_plane_url: str = "") -> httpx.Client:
    """Instance-scoped client for /instance routes; takes the raw --control-plane-url override and resolves it itself."""
    token = os.environ.get("GW_INSTANCE_KEY")
    if not token:
        console.print(f"[red]This needs an admin key. Create one at {admin_keys_url()}, then set GW_INSTANCE_KEY.[/red]")
        raise typer.Exit(1)
    return _bearer_client(token, control_plane_url)


def org_client(control_plane_url: str = "", token: str | None = None) -> httpx.Client:
    """Org-scoped client for /org routes: an explicit token, the env override, then the active login profile."""
    token = token or os.environ.get("GW_ORG_MGMT_TOKEN")
    if not token:
        profile = active_profile()
        token = str(profile["token"]) if profile and profile.get("token") else None
    if not token:
        console.print("[red]Not signed in. Run [bold]airllm login[/bold].[/red]")
        raise typer.Exit(1)
    return _bearer_client(token, control_plane_url)


def api_error(resp: httpx.Response) -> str:
    """The control plane's own explanation where it gave one, since it knows why better than we do."""
    try:
        return str(resp.json()["detail"])
    except (ValueError, KeyError, TypeError):
        return resp.text.strip() or "no details"


def ensure_ok(resp: httpx.Response) -> httpx.Response:
    """Stop on a failed request with the reason, rather than a traceback.

    raise_for_status is the wrong shape for a command line: it prints a stack through the CLI's own
    frames, which tells the reader about our call sites and not about what they should do next.
    """
    if resp.is_error:
        console.print(f"[red]Request failed ({resp.status_code}): {api_error(resp)}[/red]")
        raise typer.Exit(1)
    return resp


def payload(resp: httpx.Response) -> dict:
    """The data field of an enveloped response; every control plane response is {"data": ...}, unwrapped here and in payload_rows only."""
    return resp.json()["data"]


def payload_rows(resp: httpx.Response) -> list[dict]:
    return resp.json()["data"]


def instance_get(path: str, control_plane_url: str, params: dict | None = None) -> list[dict]:
    with instance_client(control_plane_url) as c:
        return payload_rows(ensure_ok(c.get(path, params=params or {})))


def org_get(path: str, control_plane_url: str, params: dict | None = None) -> list[dict]:
    with org_client(control_plane_url) as c:
        return payload_rows(ensure_ok(c.get(path, params=params or {})))


def resolve_workspace(workspace: str) -> str:
    """The workspace for key commands: the slug or id the caller passed, then the profile's stored default.

    Every workspace path resolves either, so nothing is looked up here; a workspace that does not
    exist is a 404 from the command itself.
    """
    if workspace:
        return workspace
    profile = active_profile() or {}
    default = profile.get("workspace") or profile.get("workspace_id")
    if default:
        return str(default)
    console.print("[red]No workspace selected. Pass --workspace, or set a default with [bold]airllm workspaces use <name>[/bold].[/red]")
    raise typer.Exit(1)


def post_expecting(client: httpx.Client, path: str, body: dict | None, ok: tuple[int, ...]) -> httpx.Response:
    resp = client.post(path, json=body)
    if resp.status_code not in ok:
        console.print(f"[red]Request failed ({resp.status_code}): {api_error(resp)}[/red]")
        raise typer.Exit(1)
    return resp
