from __future__ import annotations

import os
from typing import TYPE_CHECKING

import typer

from cli.common import console, invocation
from cli.profiles import active_profile

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


def access_client(control_plane_url: str = "", token: str | None = None) -> httpx.Client:
    profile = active_profile() or {}
    environment_token = os.environ.get("GW_ACCESS_KEY")
    selected_token = token or environment_token or profile.get("token")
    if not selected_token:
        console.print("[red]No access key available. Run [bold]airllm login[/bold] or set GW_ACCESS_KEY.[/red]")
        raise typer.Exit(1)
    return _bearer_client(str(selected_token), control_plane_url)


def resolve_org_id(override: str = "") -> str:
    selected_org = override or os.environ.get("GW_ORG_ID") or (active_profile() or {}).get("org_id")
    if selected_org:
        return str(selected_org)
    console.print("[red]No organization selected. Pass --org, set GW_ORG_ID, or sign in with [bold]airllm login[/bold].[/red]")
    raise typer.Exit(1)


def org_path(suffix: str, org_id: str = "") -> str:
    return f"/api/v1/orgs/{resolve_org_id(org_id)}{suffix}"


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


def access_get(path: str, control_plane_url: str, params: dict | None = None) -> list[dict]:
    with access_client(control_plane_url) as c:
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
