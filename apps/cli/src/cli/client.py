from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

import typer
from pydantic import BaseModel

from cli.common import console, invocation
from cli.profiles import load_active_profile

if TYPE_CHECKING:
    import httpx

QueryParams = Mapping[str, str | int | float | bool | None]
LimitOption = Annotated[int, typer.Option("--limit", min=1, max=200, help="Results to request per page")]
AllPagesOption = Annotated[bool, typer.Option("--all", help="Fetch every page")]


class _PageInfo(BaseModel):
    next_cursor: str | None


class _PageWire(BaseModel):
    data: list[object]
    page: _PageInfo | None = None


@dataclass(frozen=True)
class Page[PayloadT: BaseModel]:
    items: list[PayloadT]
    next_cursor: str | None


LOCAL_CONTROL_PLANE_URL = "http://127.0.0.1:8000"


def resolve_control_plane_url(override: str = "") -> str:
    """The control plane this run talks to.

    An explicit flag always wins, then --dev, then the environment, then the profile the last login
    wrote. --dev sits above the environment and the profile so a stale login cannot redirect a
    development run.

    airmux.yml is deliberately not consulted. It configures the two servers, which read it from
    their own working directory; a CLI run from anywhere else would either miss it or pick up a
    checkout that has nothing to do with the deployment the user is signed into.
    """
    if override:
        return override
    if invocation.dev:
        return LOCAL_CONTROL_PLANE_URL
    if url := os.environ.get("AIRMUX_CONTROL_PLANE_URL"):
        return url
    profile = load_active_profile()
    if profile and profile.control_plane_url:
        return profile.control_plane_url
    return LOCAL_CONTROL_PLANE_URL


def _bearer_client(token: str, control_plane_url: str) -> httpx.Client:
    import httpx  # noqa: PLC0415 lazy import keeps CLI startup fast

    return httpx.Client(base_url=resolve_control_plane_url(control_plane_url), headers={"authorization": f"Bearer {token}"}, timeout=10.0)


def access_client(control_plane_url: str = "", token: str | None = None) -> httpx.Client:
    profile = load_active_profile()
    environment_token = os.environ.get("AIRMUX_MANAGEMENT_KEY")
    selected_token = token or environment_token or (profile.token if profile is not None else None)
    if not selected_token:
        console.print("[red]No management key available. Run [bold]airmux login[/bold] or set AIRMUX_MANAGEMENT_KEY.[/red]")
        raise typer.Exit(1)
    return _bearer_client(str(selected_token), control_plane_url)


def resolve_org_id(override: str = "") -> str:
    profile = load_active_profile()
    selected_org = override or os.environ.get("AIRMUX_ORG_ID") or (profile.org_id if profile is not None and profile.scope == "org" else None)
    if selected_org:
        return str(selected_org)
    console.print("[red]No organization selected. Pass --org, set AIRMUX_ORG_ID, or sign in with [bold]airmux login[/bold].[/red]")
    raise typer.Exit(1)


def org_path(suffix: str, org_id: str = "") -> str:
    return f"/api/v1/organizations/{resolve_org_id(org_id)}{suffix}"


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


def payload[PayloadT: BaseModel](resp: httpx.Response, payload_type: type[PayloadT]) -> PayloadT:
    """The data field of an enveloped response; every control plane response is {"data": ...}, unwrapped here and in payload_page only."""
    return payload_type.model_validate(resp.json()["data"])


def payload_page[PayloadT: BaseModel](resp: httpx.Response, payload_type: type[PayloadT]) -> Page[PayloadT]:
    page = _PageWire.model_validate(resp.json())
    return Page(items=[payload_type.model_validate(item) for item in page.data], next_cursor=page.page.next_cursor if page.page else None)


def access_get[PayloadT: BaseModel](  # noqa: PLR0913, PLR0917 pagination controls belong at the typed request seam
    path: str,
    control_plane_url: str,
    payload_type: type[PayloadT],
    params: QueryParams | None = None,
    limit: int | None = None,
    all_pages: bool = False,
) -> list[PayloadT]:
    with access_client(control_plane_url) as c:
        query = dict(params or {})
        if limit is not None:
            query["limit"] = limit
        items: list[PayloadT] = []
        while True:
            page = payload_page(ensure_ok(c.get(path, params=query)), payload_type)
            items.extend(page.items)
            if not all_pages or page.next_cursor is None:
                return items
            query = {**query, "cursor": page.next_cursor}


def resolve_workspace(workspace: str) -> str:
    """The workspace for key commands: the slug or id the caller passed, then the profile's stored default.

    Every workspace path resolves either, so nothing is looked up here; a workspace that does not
    exist is a 404 from the command itself.
    """
    if workspace:
        return workspace
    profile = load_active_profile()
    default = profile.workspace if profile is not None and profile.scope == "org" else None
    if default:
        return str(default)
    console.print("[red]No workspace selected. Pass --workspace, or set a default with [bold]airmux workspaces use <name>[/bold].[/red]")
    raise typer.Exit(1)


def post_expecting(client: httpx.Client, path: str, body: Mapping[str, object], ok: tuple[int, ...]) -> httpx.Response:
    resp = client.post(path, json=body)
    if resp.status_code not in ok:
        console.print(f"[red]Request failed ({resp.status_code}): {api_error(resp)}[/red]")
        raise typer.Exit(1)
    return resp
