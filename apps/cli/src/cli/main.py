from __future__ import annotations

import inspect
import json
import os
import secrets
import sys
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from types import UnionType
from typing import TYPE_CHECKING, Annotated, NamedTuple, Union, get_args, get_origin

import httpx
import typer
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from dotenv import dotenv_values, find_dotenv, load_dotenv, set_key, unset_key
from pydantic import BaseModel, Field, ValidationError
from rich import box
from rich.console import Console
from rich.table import Table

from cli.api_models import KeyIn, ModelIn, OrgIn, ProviderIn
from contract import private_key_to_b64, public_key_to_b64

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic.fields import FieldInfo

app = typer.Typer(name="airllm", no_args_is_help=True)
console = Console()

SETUP = "Setup"
RESOURCES = "Resources"
TESTING = "Testing"


class OutputFormat(StrEnum):
    table = "table"
    json = "json"
    text = "text"


FormatOption = Annotated[OutputFormat, typer.Option("--format", "-f", help="Output format: table, json or text.")]


DEFAULT_CONFIG_YML = """control_plane:
  database:
    url: sqlite+aiosqlite:///airllm.db
  auth:
    admin_token: env:GW_ADMIN_TOKEN
    dp_token: env:GW_DP_TOKEN
    token_signing_key: env:GW_TOKEN_SIGNING_KEY
  bundle:
    signing_key: env:GW_BUNDLE_SIGNING_KEY
    staleness_bound_hours: 24

data_plane:
  control_plane:
    url: {control_plane_url}
    token: env:GW_DP_TOKEN
  bundle:
    public_key: env:GW_BUNDLE_PUBLIC_KEY
    cache_dir: {cache_dir}
    staleness_policy: serve_and_warn # or refuse
    poll_interval_s: 5
  auth:
    token_public_key: env:GW_TOKEN_PUBLIC_KEY
  events:
    flush_interval_s: 5
"""


def _admin_client(control_plane_url: str) -> httpx.Client:
    load_dotenv(find_dotenv(usecwd=True))
    admin_token = os.environ.get("GW_ADMIN_TOKEN")
    if not admin_token:
        console.print("[red]GW_ADMIN_TOKEN is not set, run `airllm init` first[/red]")
        raise typer.Exit(1)
    return httpx.Client(base_url=control_plane_url, headers={"authorization": f"Bearer {admin_token}"}, timeout=10.0)


def _control_plane_url(override: str) -> str:
    if override:
        return override
    if os.environ.get("GW_CONTROL_PLANE_URL"):
        return os.environ["GW_CONTROL_PLANE_URL"]
    config_path = Path(os.environ.get("GW_CONFIG", "airllm.yml"))
    if config_path.exists():
        doc = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        url = ((doc.get("data_plane") or {}).get("control_plane") or {}).get("url")
        if url:
            return str(url)
    return "http://127.0.0.1:8000"


def _admin_get(path: str, control_plane_url: str, org: str | None = None) -> list[dict]:
    load_dotenv(find_dotenv(usecwd=True))
    with _admin_client(_control_plane_url(control_plane_url)) as c:
        resp = c.get(path, params={"org_id": org} if org else {})
        resp.raise_for_status()
        return resp.json()


def _cell(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if value is None:
        return ""
    return str(value)


def _fmt_when(value: object) -> str:
    if not value:
        return ""
    return datetime.fromisoformat(str(value)).strftime("%Y-%m-%d %H:%M")


class Col(NamedTuple):
    key: str
    header: str
    style: str | None = None
    no_wrap: bool = False
    max_width: int | None = None
    fmt: Callable[[object], str] = _cell


def _print_rows(name: str, rows: list[dict], cols: list[Col], fmt: OutputFormat) -> None:
    """Every command that outputs resource data renders through here; give it a FormatOption."""
    if fmt is OutputFormat.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return
    if fmt is OutputFormat.text:
        for r in rows:
            print("\t".join(c.fmt(r.get(c.key)) for c in cols))
        return
    if not rows:
        console.print(f"No {name} found.")
        return
    table = Table(box=box.ROUNDED, header_style="bold")
    for c in cols:
        table.add_column(c.header, style=c.style, no_wrap=c.no_wrap, max_width=c.max_width)
    for r in rows:
        table.add_row(*(c.fmt(r.get(c.key)) for c in cols))
    console.print(table)


ORG_COLS = [
    Col("id", "ID", style="dim", no_wrap=True),
    Col("name", "Name", max_width=40),
    Col("created_at", "Created", no_wrap=True, fmt=_fmt_when),
]
KEY_COLS = [
    Col("id", "ID", style="dim", no_wrap=True),
    Col("org_id", "Org"),
    Col("allowed_models", "Allowed models", style="cyan", max_width=40),
    Col("disabled", "Status", style="yellow", fmt=lambda v: "revoked" if v else "active"),
    Col("created_at", "Created", no_wrap=True, fmt=_fmt_when),
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
    Col("issued_at", "Issued", no_wrap=True, fmt=_fmt_when),
    Col("expires_at", "Expires", no_wrap=True, fmt=_fmt_when),
    Col("signing_key_id", "Key", style="dim"),
]


def _load_or_create_key(key_path: Path) -> Ed25519PrivateKey:
    if key_path.exists():
        loaded = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        if not isinstance(loaded, Ed25519PrivateKey):
            console.print(f"[red]{key_path} is not an Ed25519 key[/red]")
            raise typer.Exit(1)
        return loaded
    key = Ed25519PrivateKey.generate()
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return key


@app.command(rich_help_panel=SETUP)
def init(control_plane_url: str = "http://127.0.0.1:8000", cache_dir: str = ".airllm") -> None:
    """Write secrets to .env and the shared airllm.yml config, reusing existing values."""
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    legacy = cache / "signing.key"
    if legacy.exists() and not (cache / "bundle-signing.key").exists():
        legacy.rename(cache / "bundle-signing.key")
    bundle_key = _load_or_create_key(cache / "bundle-signing.key")
    token_key = _load_or_create_key(cache / "token-signing.key")
    env_path = Path(".env")
    env_path.touch(exist_ok=True)
    existing = dotenv_values(env_path)
    values = {
        "GW_BUNDLE_SIGNING_KEY": private_key_to_b64(bundle_key),
        "GW_BUNDLE_PUBLIC_KEY": public_key_to_b64(bundle_key.public_key()),
        "GW_TOKEN_SIGNING_KEY": private_key_to_b64(token_key),
        "GW_TOKEN_PUBLIC_KEY": public_key_to_b64(token_key.public_key()),
        "GW_ADMIN_TOKEN": existing.get("GW_ADMIN_TOKEN") or secrets.token_urlsafe(24),
        "GW_DP_TOKEN": existing.get("GW_DP_TOKEN") or secrets.token_urlsafe(24),
    }
    for k, v in values.items():
        set_key(env_path, k, v)
    for stale in ("GW_CONTROL_PLANE_URL", "GW_CACHE_DIR", "GW_POLL_INTERVAL_S", "GW_SIGNING_KEY"):
        if stale in existing:
            unset_key(env_path, stale)
    console.print(f"wrote secrets to {env_path.resolve()}")
    config_path = Path(os.environ.get("GW_CONFIG", "airllm.yml"))
    if config_path.exists():
        console.print(f"kept existing {config_path}")
    else:
        config_path.write_text(DEFAULT_CONFIG_YML.format(control_plane_url=control_plane_url, cache_dir=cache), encoding="utf-8")
        console.print(f"wrote {config_path}")
    console.print("next:   [bold]uv run control-plane serve --dev[/bold]")
    console.print("        [bold]uv run airllm bootstrap[/bold]")
    console.print("        [bold]uv run data-plane --dev[/bold]")


class OrgCreate(OrgIn):
    pass


class KeyCreate(KeyIn):
    org_id: str = Field("org-dev", description="Org the key belongs to")


class ProviderCreate(ProviderIn):
    org_id: str = Field("org-dev", description="Org the provider belongs to")


class ModelCreate(ModelIn):
    org_id: str = Field("org-dev", description="Org the model belongs to")


class BootstrapSpec(BaseModel):
    org: str
    providers: list[ProviderCreate] = Field(default_factory=list)
    models: list[ModelCreate] = Field(default_factory=list)
    keys: list[KeyCreate] = Field(default_factory=lambda: [KeyCreate()])


def _post_expecting(client: httpx.Client, path: str, body: dict, ok: tuple[int, ...]) -> httpx.Response:
    resp = client.post(path, json=body)
    if resp.status_code not in ok:
        console.print(f"[red]POST {path} failed: {resp.status_code} {resp.text}[/red]")
        raise typer.Exit(1)
    return resp


@app.command(rich_help_panel=SETUP)
def bootstrap(file: str = "bootstrap.yml", control_plane_url: str = "") -> None:
    """Apply a YAML spec (org, providers, models, keys) through the admin API and compile a bundle."""
    path = Path(file)
    if not path.exists():
        console.print(f"[red]{file} not found[/red]")
        raise typer.Exit(1)
    spec = BootstrapSpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    load_dotenv(find_dotenv(usecwd=True))
    cp_url = _control_plane_url(control_plane_url)
    with _admin_client(cp_url) as c:
        _post_expecting(c, "/admin/orgs", {"id": spec.org}, ok=(200, 409))
        for provider in spec.providers:
            _post_expecting(c, "/admin/providers", {**provider.model_dump(mode="json"), "org_id": spec.org}, ok=(200, 409))
        for model in spec.models:
            _post_expecting(c, "/admin/models", {**model.model_dump(mode="json"), "org_id": spec.org}, ok=(200, 409))
        minted = [
            _post_expecting(c, "/admin/keys", {"org_id": spec.org, "allowed_models": key.allowed_models}, ok=(200,)).json() for key in spec.keys
        ]
        compiled = _post_expecting(c, "/admin/bundles/compile", {"org_id": spec.org}, ok=(200,)).json()
    for key in minted:
        console.print(f"key [bold]{key['key_id']}[/bold] minted")
    if minted:
        env_path = Path(".env")
        env_path.touch(exist_ok=True)
        set_key(env_path, "AIRLLM_TOKEN", minted[0]["token"])
        console.print("first token saved to .env as AIRLLM_TOKEN")
    console.print(f"bundle [bold]{compiled['bundle_id']}[/bold] v{compiled['version']} compiled, data plane picks it up within one poll interval")


orgs_app = typer.Typer(help="Orgs")
keys_app = typer.Typer(help="Caller API keys")
providers_app = typer.Typer(help="Upstream providers")
models_app = typer.Typer(help="Routable models")
bundles_app = typer.Typer(help="Signed policy bundles")
for name, sub in (("orgs", orgs_app), ("keys", keys_app), ("providers", providers_app), ("models", models_app), ("bundles", bundles_app)):
    app.add_typer(sub, name=name, rich_help_panel=RESOURCES, no_args_is_help=True)


@orgs_app.command("list")
def orgs_list(control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List orgs."""
    _print_rows("orgs", _admin_get("/admin/orgs", control_plane_url), ORG_COLS, fmt)


@keys_app.command("list")
def keys_list(org: str | None = None, control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List caller API keys with their status."""
    _print_rows("keys", _admin_get("/admin/keys", control_plane_url, org), KEY_COLS, fmt)


@keys_app.command("revoke")
def keys_revoke(key_id: str, control_plane_url: str = "") -> None:
    """Disable a key; lands in revocations at the next compile."""
    with _admin_client(_control_plane_url(control_plane_url)) as c:
        resp = c.delete(f"/admin/keys/{key_id}")
        resp.raise_for_status()
    console.print(f"key [bold]{key_id}[/bold] revoked, run `airllm bundles compile` to propagate")


@providers_app.command("list")
def providers_list(org: str | None = None, control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List upstream providers and their credential references."""
    _print_rows("providers", _admin_get("/admin/providers", control_plane_url, org), PROVIDER_COLS, fmt)


@models_app.command("list")
def models_list(org: str | None = None, control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List routable models with pricing and capabilities."""
    _print_rows("models", _admin_get("/admin/models", control_plane_url, org), MODEL_COLS, fmt)


@bundles_app.command("list")
def bundles_list(org: str | None = None, control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List compiled bundle versions and their validity windows."""
    _print_rows("bundles", _admin_get("/admin/bundles", control_plane_url, org), BUNDLE_COLS, fmt)


@bundles_app.command("compile")
def bundles_compile(org: str = "org-dev", control_plane_url: str = "") -> None:
    """Recompile and sign the bundle for an org."""
    load_dotenv(find_dotenv(usecwd=True))
    with _admin_client(_control_plane_url(control_plane_url)) as c:
        resp = c.post("/admin/bundles/compile", json={"org_id": org})
        resp.raise_for_status()
        compiled = resp.json()
    console.print(f"bundle [bold]{compiled['bundle_id']}[/bold] v{compiled['version']} compiled")


def _base_annotation(ann: object) -> object:
    if get_origin(ann) in (UnionType, Union):
        args = [a for a in get_args(ann) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return ann


def _is_list_field(field: FieldInfo) -> bool:
    return get_origin(_base_annotation(field.annotation)) is list


def _flag_annotation(field: FieldInfo) -> object:
    base = _base_annotation(field.annotation)
    if get_origin(base) is list:
        return list[str] | None
    return (base | None) if base in (str, float, int) else (str | None)


def _fill_spec(spec_cls: type[BaseModel], provided: dict) -> BaseModel:
    """Flags win; anything missing is prompted for, with the field description as the prompt."""
    values = {k: v for k, v in provided.items() if v not in (None, [], ())}
    for name, field in spec_cls.model_fields.items():
        if name in values:
            continue
        has_default = not field.is_required()
        if not sys.stdin.isatty():
            if has_default:
                continue
            console.print(f"[red]missing --{name.replace('_', '-')} and no terminal to prompt for it[/red]")
            raise typer.Exit(1)
        label = field.description or name.replace("_", " ")
        default = field.get_default(call_default_factory=True) if has_default else None
        raw = typer.prompt(label, default=",".join(default) if isinstance(default, list) else default)
        values[name] = [part.strip() for part in str(raw).split(",") if part.strip()] if _is_list_field(field) else raw
    try:
        return spec_cls.model_validate(values)
    except ValidationError as e:
        for err in e.errors():
            console.print(f"[red]{'.'.join(str(x) for x in err['loc'])}: {err['msg']}[/red]")
        raise typer.Exit(1) from e


def _register_create(sub_app: typer.Typer, spec_cls: type[BaseModel], path: str, help_text: str, done: Callable[[dict], None]) -> None:
    """Derive a create command from a spec model: one flag and one prompt per field, never hardcoded."""

    def run(**kwargs: object) -> None:
        control_plane_url = str(kwargs.pop("control_plane_url", "") or "")
        spec = _fill_spec(spec_cls, kwargs)
        with _admin_client(_control_plane_url(control_plane_url)) as c:
            resp = _post_expecting(c, path, spec.model_dump(mode="json"), ok=(200,))
        done(resp.json())

    params = [
        inspect.Parameter(
            name,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            default=typer.Option(None, help=field.description),
            annotation=_flag_annotation(field),
        )
        for name, field in spec_cls.model_fields.items()
    ]
    params.append(inspect.Parameter("control_plane_url", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=typer.Option(""), annotation=str))
    run.__signature__ = inspect.Signature(params)  # type: ignore[attr-defined]
    run.__doc__ = help_text
    sub_app.command("create")(run)


def _key_created(resp: dict) -> None:
    console.print(f"key [bold]{resp['key_id']}[/bold] minted, token (shown once):")
    console.print(resp["token"])
    console.print("[dim]run `airllm bundles compile` to include it in the next bundle[/dim]")


_register_create(
    orgs_app,
    OrgCreate,
    "/admin/orgs",
    "Create an org; keys, providers and models hang off it.",
    lambda resp: console.print(f"org [bold]{resp['id']}[/bold] created"),
)
_register_create(keys_app, KeyCreate, "/admin/keys", "Mint a key; the token is shown once and never stored.", _key_created)
_register_create(
    providers_app,
    ProviderCreate,
    "/admin/providers",
    "Register an upstream provider.",
    lambda resp: console.print(f"provider [bold]{resp['provider_id']}[/bold] created, add models then `airllm bundles compile`"),
)
_register_create(
    models_app,
    ModelCreate,
    "/admin/models",
    "Add a routable model.",
    lambda resp: console.print(f"model [bold]{resp['model_id']}[/bold] created, run `airllm bundles compile` to serve it"),
)


test_app = typer.Typer(help="Acceptance and load testing", no_args_is_help=True)
app.add_typer(test_app, name="test", rich_help_panel=TESTING)


@test_app.command()
def verify() -> None:
    """Run the acceptance checks against a running gateway. Not implemented yet."""
    raise NotImplementedError


@test_app.command()
def loadgen() -> None:
    """Generate request load against the data plane. Not implemented yet."""
    raise NotImplementedError
