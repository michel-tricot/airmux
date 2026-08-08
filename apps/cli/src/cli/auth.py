from __future__ import annotations

import os
import socket
import time
import webbrowser
from typing import TYPE_CHECKING

import typer
from rich.panel import Panel

if TYPE_CHECKING:
    import httpx

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

CSRF = {"X-Requested-With": "airllm-cli"}


def _client_name() -> str:
    return f"cli@{socket.gethostname()}"


def _payload_or_die(resp: httpx.Response, what: str) -> dict:
    if not resp.is_success:
        console.print(f"[red]{what} failed: {resp.status_code} {resp.text}[/red]")
        raise typer.Exit(1)
    return payload(resp)


def _step(done: str) -> None:
    console.print(f"  [green]✓[/green] {done}")


@app.command(rich_help_panel=SETUP)
def quickstart(  # noqa: PLR0913, PLR0917 flags are the command's interface
    control_plane_url: str = "",
    email: str = typer.Option(..., prompt="Email", help="Email for the first account"),
    password: str = typer.Option(..., prompt="Password", hide_input=True, confirmation_prompt=True, help="At least 8 characters"),
    org: str = typer.Option("", help="Org name to create; defaults to the email local part"),
    gateway_url: str = typer.Option("http://localhost:8080", help="Where the data plane serves, for the printed example"),
    webapp_url: str = typer.Option("http://localhost:3000", help="Where the console is served, printed at the end"),
) -> None:
    """Bootstrap a fresh instance end to end: account, org, tokens, data plane, and a ready-to-use inference key."""
    import httpx  # noqa: PLC0415 lazy import keeps CLI startup fast

    url = resolve_control_plane_url(control_plane_url)
    console.rule("[bold]airllm quickstart")
    with httpx.Client(base_url=url, timeout=10.0, headers=CSRF) as c:
        if _payload_or_die(c.get("/v1/instance/oss/claim"), "claim check")["claimed"]:
            console.print(f"[red]this instance is already set up; run [bold]airllm login[/bold] against {url} instead[/red]")
            raise typer.Exit(1)

        _payload_or_die(c.post("/v1/auth/signup", json={"email": email, "name": email, "password": password}), "sign up")
        _step(f"created account [bold]{email}[/bold]")

        created = _payload_or_die(c.post("/v1/enroll/org", json={"name": org or email.split("@", maxsplit=1)[0]}), "org creation")
        org_id, org_name = created["id"], created["name"]
        _step(f"created org [bold]{org_name}[/bold]")

        started = _payload_or_die(c.post("/v1/auth/cli/start", json={"client_name": _client_name()}), "token request")
        _payload_or_die(c.post("/v1/auth/cli/approve", json={"user_code": started["user_code"], "org_id": org_id}), "token approval")
        token = _payload_or_die(c.post("/v1/auth/cli/poll", json={"poll_secret": started["poll_secret"]}), "token delivery")["token"]
        upsert_profile(org_name, {"control_plane_url": url, "org_id": org_id, "org_name": org_name, "token": token})
        _step(f"minted management token, saved to {config_path()}")

        quick = c.post("/v1/instance/oss/quickstart", json={"token": token})
        if quick.is_success:
            _step("dropped the data plane token; it will come online shortly")
        else:
            console.print(f"  [yellow]![/yellow] could not drop the data plane token ({quick.status_code}); set GW_DATAPLANE_TOKEN yourself")

        bearer = {"authorization": f"Bearer {token}"}
        key = _payload_or_die(c.post("/v1/org/keys", json={"label": "quickstart"}, headers=bearer), "key mint")
        compiled = _payload_or_die(c.post("/v1/org/bundles/compile", json={}, headers=bearer), "bundle compile")
        _step(f"minted an inference key and compiled bundle v{compiled['version']}")

    curl = (
        f"curl {gateway_url}/v1/chat/completions \\\n"
        f"  -H 'Authorization: Bearer {key['token']}' \\\n"
        f"  -H 'Content-Type: application/json' \\\n"
        f'  -d \'{{"model": "gpt-4o", "messages": [{{"role": "user", "content": "hi"}}]}}\''
    )
    console.print(f"\n[green]ready[/green]  org [bold]{org_name}[/bold], token saved to {config_path()}")
    console.print(Panel(key["token"], title="AIRLLM_API_KEY", border_style="cyan", expand=False))
    console.print("[dim]try it once the data plane is online[/dim]")
    print(curl)
    console.print(f"\n[dim]webapp[/dim] {webapp_url}")


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
