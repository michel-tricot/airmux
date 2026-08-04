from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Literal

import httpx
import typer
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from dotenv import dotenv_values, find_dotenv, load_dotenv, set_key, unset_key
from pydantic import BaseModel, Field

from contract import private_key_to_b64, public_key_to_b64

app = typer.Typer(name="airllm", no_args_is_help=True)


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
        typer.echo("GW_ADMIN_TOKEN is not set, run `airllm init` first", err=True)
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


@app.command()
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
    typer.echo(f"wrote secrets to {env_path.resolve()}")
    config_path = Path(os.environ.get("GW_CONFIG", "airllm.yml"))
    if config_path.exists():
        typer.echo(f"kept existing {config_path}")
    else:
        config_path.write_text(DEFAULT_CONFIG_YML.format(control_plane_url=control_plane_url, cache_dir=cache), encoding="utf-8")
        typer.echo(f"wrote {config_path}")
    typer.echo("next:   uv run control-plane serve --dev")
    typer.echo("        uv run airllm bootstrap")
    typer.echo("        uv run data-plane --dev")


class ProviderSpec(BaseModel):
    provider_id: str
    kind: Literal["openai_compatible", "anthropic"] = "openai_compatible"
    base_url: str
    credential_ref: str


class ModelSpec(BaseModel):
    model_id: str
    provider_id: str
    upstream_model: str = ""
    input_price_per_mtok: float = 0.0
    output_price_per_mtok: float = 0.0
    context_window: int = 128000
    capabilities: list[str] = Field(default_factory=lambda: ["streaming", "tools"])


class KeySpec(BaseModel):
    allowed_models: list[str] = Field(default_factory=lambda: ["*"])


class BootstrapSpec(BaseModel):
    org: str
    providers: list[ProviderSpec] = Field(default_factory=list)
    models: list[ModelSpec] = Field(default_factory=list)
    keys: list[KeySpec] = Field(default_factory=lambda: [KeySpec()])


def _post_expecting(client: httpx.Client, path: str, body: dict, ok: tuple[int, ...]) -> httpx.Response:
    resp = client.post(path, json=body)
    if resp.status_code not in ok:
        typer.echo(f"POST {path} failed: {resp.status_code} {resp.text}", err=True)
        raise typer.Exit(1)
    return resp


@app.command()
def bootstrap(file: str = "bootstrap.yml", control_plane_url: str = "") -> None:
    """Apply a YAML spec (org, providers, models, keys) through the admin API and compile a bundle."""
    path = Path(file)
    if not path.exists():
        typer.echo(f"{file} not found", err=True)
        raise typer.Exit(1)
    spec = BootstrapSpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    load_dotenv(find_dotenv(usecwd=True))
    cp_url = _control_plane_url(control_plane_url)
    with _admin_client(cp_url) as c:
        _post_expecting(c, "/admin/orgs", {"id": spec.org}, ok=(200, 409))
        for provider in spec.providers:
            _post_expecting(c, "/admin/providers", {"org_id": spec.org, **provider.model_dump()}, ok=(200, 409))
        for model in spec.models:
            _post_expecting(c, "/admin/models", {"org_id": spec.org, **model.model_dump()}, ok=(200, 409))
        minted = [
            _post_expecting(c, "/admin/keys", {"org_id": spec.org, "allowed_models": key.allowed_models}, ok=(200,)).json() for key in spec.keys
        ]
        compiled = _post_expecting(c, "/admin/bundles/compile", {"org_id": spec.org}, ok=(200,)).json()
    for key in minted:
        typer.echo(f"key {key['key_id']} minted")
    if minted:
        env_path = Path(".env")
        env_path.touch(exist_ok=True)
        set_key(env_path, "AIRLLM_TOKEN", minted[0]["token"])
        typer.echo("first token saved to .env as AIRLLM_TOKEN")
    typer.echo(f"bundle {compiled['bundle_id']} v{compiled['version']} compiled, data plane picks it up within one poll interval")


def _load_or_create_key(key_path: Path) -> Ed25519PrivateKey:
    if key_path.exists():
        loaded = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        if not isinstance(loaded, Ed25519PrivateKey):
            typer.echo(f"{key_path} is not an Ed25519 key", err=True)
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


@app.command("compile")
def compile_bundle(org: str = "org-dev", control_plane_url: str = "") -> None:
    """Recompile and sign the bundle for an org through the control plane."""
    load_dotenv(find_dotenv(usecwd=True))
    cp_url = _control_plane_url(control_plane_url)
    with _admin_client(cp_url) as c:
        resp = c.post("/admin/bundles/compile", json={"org_id": org})
        resp.raise_for_status()
        compiled = resp.json()
    typer.echo(f"bundle {compiled['bundle_id']} v{compiled['version']} compiled")


list_app = typer.Typer(help="Read resources from the control plane")
app.add_typer(list_app, name="list")


def _admin_get(path: str, control_plane_url: str, org: str | None = None) -> list[dict]:
    load_dotenv(find_dotenv(usecwd=True))
    with _admin_client(_control_plane_url(control_plane_url)) as c:
        resp = c.get(path, params={"org_id": org} if org else {})
        resp.raise_for_status()
        return resp.json()


def _print_table(rows: list[dict]) -> None:
    if not rows:
        typer.echo("(none)")
        return
    cols = list(dict.fromkeys(k for r in rows for k in r))
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    typer.echo("  ".join(c.ljust(widths[c]) for c in cols))
    for r in rows:
        typer.echo("  ".join(str(r.get(c, "")).ljust(widths[c]) for c in cols))


@list_app.command("orgs")
def list_orgs(control_plane_url: str = "") -> None:
    _print_table(_admin_get("/admin/orgs", control_plane_url))


@list_app.command("keys")
def list_keys(org: str | None = None, control_plane_url: str = "") -> None:
    _print_table(_admin_get("/admin/keys", control_plane_url, org))


@list_app.command("providers")
def list_providers(org: str | None = None, control_plane_url: str = "") -> None:
    _print_table(_admin_get("/admin/providers", control_plane_url, org))


@list_app.command("models")
def list_models(org: str | None = None, control_plane_url: str = "") -> None:
    _print_table(_admin_get("/admin/models", control_plane_url, org))


@list_app.command("bundles")
def list_bundles(org: str | None = None, control_plane_url: str = "") -> None:
    _print_table(_admin_get("/admin/bundles", control_plane_url, org))


@app.command()
def verify() -> None:
    raise NotImplementedError


@app.command()
def loadgen() -> None:
    raise NotImplementedError
