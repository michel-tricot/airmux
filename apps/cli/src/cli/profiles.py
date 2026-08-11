from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

import tomli_w


def config_path() -> Path:
    if override := os.environ.get("GW_CLI_CONFIG"):
        return Path(override)
    return Path.home() / ".airllm" / "config.toml"


def load_config() -> dict[str, Any]:
    path = config_path()
    if path.exists():
        return tomllib.loads(path.read_text(encoding="utf-8"))
    return {}


def save_config(config: dict[str, Any]) -> None:
    """Write the whole config; the file holds tokens, so it is chmod 0600 on every write."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomli_w.dumps(config), encoding="utf-8")
    path.chmod(0o600)


def active_profile(config: dict[str, Any] | None = None) -> dict[str, Any] | None:
    config = load_config() if config is None else config
    profiles = config.get("profiles") or {}
    name = config.get("active")
    if isinstance(name, str) and name in profiles:
        return {"name": name, **profiles[name]}
    return None


def upsert_profile(name: str, values: dict[str, Any], *, activate: bool = True) -> None:
    config = load_config()
    profiles = dict(config.get("profiles") or {})
    profiles[name] = values
    updated = {**config, "profiles": profiles, **({"active": name} if activate else {})}
    save_config(updated)


def set_active(name: str) -> None:
    save_config({**load_config(), "active": name})


DEFAULT_CONSOLE_URL = "http://localhost:5000"
ADMIN_KEYS_PATH = "/instance/keys"


def admin_keys_url() -> str:
    """Where an instance admin mints their first admin key.

    Held here rather than derived at the call site because the commands that refuse for want of one
    are the commands with no credential to ask the control plane anything with.
    """
    profile = active_profile() or {}
    return str(profile.get("console_url") or DEFAULT_CONSOLE_URL).rstrip("/") + ADMIN_KEYS_PATH
