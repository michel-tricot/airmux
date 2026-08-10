from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import typer
import yaml

from cli.common import console
from cli.profiles import active_profile

if TYPE_CHECKING:
    import httpx


def resolve_control_plane_url(override: str) -> str:
    if override:
        return override
    if url := os.environ.get("GW_CONTROL_PLANE_URL"):
        return url
    profile = active_profile()
    if profile and profile.get("control_plane_url"):
        return str(profile["control_plane_url"])
    config_path = Path(os.environ.get("GW_CONFIG", "airllm.yml"))
    if config_path.exists():
        doc = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        url = ((doc.get("data_plane") or {}).get("control_plane") or {}).get("url")
        if url:
            return str(url)
    return "http://127.0.0.1:8000"


def _bearer_client(token: str, control_plane_url: str) -> httpx.Client:
    import httpx  # noqa: PLC0415 lazy import keeps CLI startup fast

    return httpx.Client(base_url=resolve_control_plane_url(control_plane_url), headers={"authorization": f"Bearer {token}"}, timeout=10.0)


def instance_client(control_plane_url: str = "") -> httpx.Client:
    """Instance-scoped client for /instance routes; takes the raw --control-plane-url override and resolves it itself."""
    token = os.environ.get("GW_INSTANCE_KEY")
    if not token:
        console.print("[red]GW_INSTANCE_KEY is not set; this command needs an instance key (`airllm instance-keys mint`)[/red]")
        raise typer.Exit(1)
    return _bearer_client(token, control_plane_url)


def org_client(control_plane_url: str = "", token: str | None = None) -> httpx.Client:
    """Org-scoped client for /org routes: an explicit token, the env override, then the active login profile."""
    token = token or os.environ.get("GW_ORG_MGMT_TOKEN")
    if not token:
        profile = active_profile()
        token = str(profile["token"]) if profile and profile.get("token") else None
    if not token:
        console.print("[red]no org management key: run `airllm login`[/red]")
        raise typer.Exit(1)
    return _bearer_client(token, control_plane_url)


def payload(resp: httpx.Response) -> dict:
    """The data field of an enveloped response; every control plane response is {"data": ...}, unwrapped here and in payload_rows only."""
    return resp.json()["data"]


def payload_rows(resp: httpx.Response) -> list[dict]:
    return resp.json()["data"]


def instance_get(path: str, control_plane_url: str, params: dict | None = None) -> list[dict]:
    with instance_client(control_plane_url) as c:
        resp = c.get(path, params=params or {})
        resp.raise_for_status()
        return payload_rows(resp)


def org_get(path: str, control_plane_url: str, params: dict | None = None) -> list[dict]:
    with org_client(control_plane_url) as c:
        resp = c.get(path, params=params or {})
        resp.raise_for_status()
        return payload_rows(resp)


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
    console.print("[red]no workspace: pass --workspace or run `airllm workspaces use <name>`[/red]")
    raise typer.Exit(1)


def post_expecting(client: httpx.Client, path: str, body: dict | None, ok: tuple[int, ...]) -> httpx.Response:
    resp = client.post(path, json=body)
    if resp.status_code not in ok:
        console.print(f"[red]POST {path} failed: {resp.status_code} {resp.text}[/red]")
        raise typer.Exit(1)
    return resp
