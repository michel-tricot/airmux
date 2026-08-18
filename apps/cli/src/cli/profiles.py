from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

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


def upsert_url_profile(name: str, values: dict[str, Any], *, activate: bool = True) -> str:
    config = load_config()
    profiles = dict(config.get("profiles") or {})
    control_plane_url = str(values.get("control_plane_url", "")).rstrip("/")
    matching = next(
        (
            profile_name
            for profile_name, profile in profiles.items()
            if (profile_name == name or profile.get("org_name") == name)
            and str(profile.get("control_plane_url", "")).rstrip("/") == control_plane_url
        ),
        None,
    )
    if matching is not None:
        profile_name = matching
    elif name not in profiles:
        profile_name = name
    else:
        host = urlsplit(control_plane_url).hostname or "deployment"
        candidate = f"{name}@{host}"
        suffix = 2
        while candidate in profiles:
            candidate = f"{name}@{host}-{suffix}"
            suffix += 1
        profile_name = candidate
    updated_profiles = {**profiles, profile_name: values}
    updated = {**config, "profiles": updated_profiles, **({"active": profile_name} if activate else {})}
    save_config(updated)
    return profile_name


def set_active(name: str) -> None:
    save_config({**load_config(), "active": name})


DEFAULT_CONSOLE_URL = "http://localhost:5000"
