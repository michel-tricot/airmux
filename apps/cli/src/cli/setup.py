from __future__ import annotations

import os
import secrets
from pathlib import Path

import typer
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from dotenv import dotenv_values, set_key, unset_key

from cli.client import admin_client, post_expecting, resolve_control_plane_url
from cli.common import SETUP, app, console
from cli.specs import BootstrapSpec
from contract import private_key_to_b64, public_key_to_b64

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
    org: org-dev
    cache_dir: {cache_dir}
    staleness_policy: serve_and_warn # or refuse
    poll_interval_s: 5
  auth:
    token_public_key: env:GW_TOKEN_PUBLIC_KEY
  events:
    flush_interval_s: 5
"""


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


@app.command(rich_help_panel=SETUP)
def bootstrap(file: str = "bootstrap.yml", control_plane_url: str = "") -> None:
    """Apply a YAML spec (org, providers, models, keys) through the admin API and compile a bundle."""
    path = Path(file)
    if not path.exists():
        console.print(f"[red]{file} not found[/red]")
        raise typer.Exit(1)
    spec = BootstrapSpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    cp_url = resolve_control_plane_url(control_plane_url)
    with admin_client(cp_url) as c:
        post_expecting(c, "/admin/orgs", {"id": spec.org}, ok=(200, 409))
        for provider in spec.providers:
            post_expecting(c, "/admin/providers", {**provider.model_dump(mode="json"), "org_id": spec.org}, ok=(200, 409))
        for model in spec.models:
            post_expecting(c, "/admin/models", {**model.model_dump(mode="json"), "org_id": spec.org}, ok=(200, 409))
        minted = [post_expecting(c, "/admin/keys", {"org_id": spec.org, "allowed_models": key.allowed_models}, ok=(200,)).json() for key in spec.keys]
        compiled = post_expecting(c, "/admin/bundles/compile", {"org_id": spec.org}, ok=(200,)).json()
    for key in minted:
        console.print(f"key [bold]{key['key_id']}[/bold] minted")
    if minted:
        env_path = Path(".env")
        env_path.touch(exist_ok=True)
        set_key(env_path, "AIRLLM_TOKEN", minted[0]["token"])
        console.print("first token saved to .env as AIRLLM_TOKEN")
    console.print(f"bundle [bold]{compiled['bundle_id']}[/bold] v{compiled['version']} compiled, data plane picks it up within one poll interval")
