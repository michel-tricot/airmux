from __future__ import annotations

import os
import socket
import time
import webbrowser

import typer

from cli.client import payload, resolve_control_plane_url
from cli.common import SETUP, app, console, orgs_app
from cli.output import Col, FormatOption, OutputFormat, print_rows
from cli.profiles import config_path, load_config, set_active, upsert_profile

MINE_COLS = [
    Col("id", "ID", style="dim", no_wrap=True),
    Col("name", "Name", max_width=40),
    Col("kind", "Kind"),
]


HTTP_GONE = 410


def _client_name() -> str:
    return f"cli@{socket.gethostname()}"


@app.command(rich_help_panel=SETUP)
def login(
    control_plane_url: str = "",
    no_browser: bool = typer.Option(False, "--no-browser", help="Print the URL instead of opening a browser"),
) -> None:
    """Log in through the browser and store this machine's org token; signup and org setup happen there too."""
    import httpx  # noqa: PLC0415 lazy import keeps CLI startup fast

    url = resolve_control_plane_url(control_plane_url)
    client_name = _client_name()
    with httpx.Client(base_url=url, timeout=10.0) as c:
        resp = c.post("/v1/auth/cli/start", json={"client_name": client_name})
        resp.raise_for_status()
        started = payload(resp)
        console.print(f"Confirm code [bold]{started['user_code']}[/bold] in your browser: {started['verification_url']}")
        if not no_browser:
            webbrowser.open(started["verification_url"])
        deadline = time.monotonic() + started["expires_in_seconds"]
        while time.monotonic() < deadline:
            time.sleep(started["interval_seconds"])
            poll = c.post("/v1/auth/cli/poll", json={"poll_secret": started["poll_secret"]})
            if poll.status_code == HTTP_GONE:
                console.print("[red]the login request expired before it was approved, run `airllm login` again[/red]")
                raise typer.Exit(1)
            poll.raise_for_status()
            done = payload(poll)
            if done["status"] == "complete":
                upsert_profile(
                    done["org_name"],
                    {"control_plane_url": url, "org_id": done["org_id"], "org_name": done["org_name"], "token": done["token"]},
                )
                console.print(f"Logged in to [bold]{done['org_name']}[/bold]; token stored in {config_path()} as the active profile.")
                return
    console.print("[red]login timed out, run `airllm login` again[/red]")
    raise typer.Exit(1)


@orgs_app.command("switch")
def orgs_switch(name: str, control_plane_url: str = "") -> None:
    """Make an org's stored token the active one; runs the browser login when none is stored."""
    if os.environ.get("GW_ORG_MGMT_TOKEN"):
        console.print("[yellow]GW_ORG_MGMT_TOKEN is set and overrides stored profiles; unset it for the switch to take effect[/yellow]")
    config = load_config()
    if name in (config.get("profiles") or {}):
        set_active(name)
        console.print(f"switched to [bold]{name}[/bold]")
        return
    console.print(f"no stored token for [bold]{name}[/bold], starting browser login; pick [bold]{name}[/bold] on the approve page")
    login(control_plane_url=control_plane_url)
    active = load_config().get("active")
    if active != name:
        console.print(f"[yellow]you approved [bold]{active}[/bold], not {name}; it is now the active profile[/yellow]")


@orgs_app.command("mine")
def orgs_mine(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List the orgs you belong to, via the stored login."""
    from cli.client import org_client  # noqa: PLC0415 lazy import keeps CLI startup fast

    with org_client(control_plane_url) as c:
        resp = c.get("/v1/enroll")
        resp.raise_for_status()
        standing = payload(resp)
        rows = [{**org, "kind": "personal" if org["id"] == standing["personal_org_id"] else "member"} for org in standing["orgs"]]
        print_rows("orgs", rows, MINE_COLS, fmt)
