from __future__ import annotations

from cli.client import admin_client, admin_get, post_expecting
from cli.common import bundles_app, console, keys_app, models_app, orgs_app, providers_app
from cli.forms import register_create
from cli.output import Col, FormatOption, OutputFormat, fmt_when, print_rows
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
    Col("capabilities", "Capabilities", style="cyan", max_width=30),
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
