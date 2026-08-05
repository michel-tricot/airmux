from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import dotenv_values, set_key, unset_key

from cli.common import SETUP, app, console

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

DEFAULT_CONFIG_YML = """control_plane:
  database:
    url: sqlite+aiosqlite:///airllm.db
  auth:
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


@app.command(rich_help_panel=SETUP)
def init(control_plane_url: str = "http://127.0.0.1:8000", cache_dir: str = ".airllm") -> None:
    """Write secrets to .env and the shared airllm.yml config, reusing existing values."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: PLC0415 lazy import keeps CLI startup fast

    from contract import private_key_from_b64, private_key_to_b64, public_key_to_b64  # noqa: PLC0415 lazy import keeps CLI startup fast

    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    env_path = Path(".env")
    env_path.touch(exist_ok=True)
    existing = dotenv_values(env_path)

    def signing_key(env_name: str) -> Ed25519PrivateKey:
        stored = existing.get(env_name)
        return private_key_from_b64(stored) if stored else Ed25519PrivateKey.generate()

    bundle_key = signing_key("GW_BUNDLE_SIGNING_KEY")
    token_key = signing_key("GW_TOKEN_SIGNING_KEY")
    values = {
        "GW_BUNDLE_SIGNING_KEY": private_key_to_b64(bundle_key),
        "GW_BUNDLE_PUBLIC_KEY": public_key_to_b64(bundle_key.public_key()),
        "GW_TOKEN_SIGNING_KEY": private_key_to_b64(token_key),
        "GW_TOKEN_PUBLIC_KEY": public_key_to_b64(token_key.public_key()),
    }
    for k, v in values.items():
        set_key(env_path, k, v)
    for stale in ("GW_CONTROL_PLANE_URL", "GW_CACHE_DIR", "GW_POLL_INTERVAL_S", "GW_SIGNING_KEY", "GW_ADMIN_TOKEN"):
        if stale in existing:
            unset_key(env_path, stale)
    console.print(f"wrote secrets to {env_path.resolve()}")
    config_path = Path(os.environ.get("GW_CONFIG", "airllm.yml"))
    if config_path.exists():
        console.print(f"kept existing {config_path}")
    else:
        config_path.write_text(DEFAULT_CONFIG_YML.format(control_plane_url=control_plane_url, cache_dir=cache_dir), encoding="utf-8")
        console.print(f"wrote {config_path}")
    console.print("next:   [bold]uv run control-plane mint-root-token[/bold]")
    console.print("        [bold]uv run control-plane serve --dev[/bold]  (first start applies bootstrap.yml and mints tokens into .env)")
    console.print("        [bold]uv run data-plane --dev[/bold]")
