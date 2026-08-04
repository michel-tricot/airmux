from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import typer

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
        import yaml  # noqa: PLC0415 lazy import keeps CLI startup fast

        doc = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        url = ((doc.get("data_plane") or {}).get("control_plane") or {}).get("url")
        if url:
            return str(url)
    return "http://127.0.0.1:8000"


def admin_client(control_plane_url: str = "") -> httpx.Client:
    """Takes the raw --control-plane-url override and resolves it itself."""
    import httpx  # noqa: PLC0415 lazy import keeps CLI startup fast

    admin_token = os.environ.get("GW_ADMIN_TOKEN")
    if not admin_token:
        console.print("[red]GW_ADMIN_TOKEN is not set, run `airllm init` first[/red]")
        raise typer.Exit(1)
    return httpx.Client(base_url=resolve_control_plane_url(control_plane_url), headers={"authorization": f"Bearer {admin_token}"}, timeout=10.0)


def admin_get(path: str, control_plane_url: str, org: str | None = None) -> list[dict]:
    with admin_client(control_plane_url) as c:
        resp = c.get(path, params={"org_id": org} if org else {})
        resp.raise_for_status()
        return resp.json()


def post_expecting(client: httpx.Client, path: str, body: dict, ok: tuple[int, ...]) -> httpx.Response:
    resp = client.post(path, json=body)
    if resp.status_code not in ok:
        console.print(f"[red]POST {path} failed: {resp.status_code} {resp.text}[/red]")
        raise typer.Exit(1)
    return resp
