from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import typer
import yaml

from cli.common import console

if TYPE_CHECKING:
    import httpx


def resolve_control_plane_url(override: str) -> str:
    if override:
        return override
    if url := os.environ.get("GW_CONTROL_PLANE_URL"):
        return url
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
    token = os.environ.get("GW_ADMIN_MGMT_TOKEN")
    if not token:
        console.print("[red]GW_ADMIN_MGMT_TOKEN is not set, run `airllmcp init` first[/red]")
        raise typer.Exit(1)
    return _bearer_client(token, control_plane_url)


def org_client(control_plane_url: str = "", token: str | None = None) -> httpx.Client:
    """Org-scoped client for /org routes; the token comes from `airllmcp init` or `airllm tokens mint`."""
    token = token or os.environ.get("GW_ORG_MGMT_TOKEN")
    if not token:
        console.print("[red]GW_ORG_MGMT_TOKEN is not set, run `airllmcp init` or `airllm tokens mint <org>` first[/red]")
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


def post_expecting(client: httpx.Client, path: str, body: dict | None, ok: tuple[int, ...]) -> httpx.Response:
    resp = client.post(path, json=body)
    if resp.status_code not in ok:
        console.print(f"[red]POST {path} failed: {resp.status_code} {resp.text}[/red]")
        raise typer.Exit(1)
    return resp
