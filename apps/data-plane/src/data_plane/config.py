from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import find_dotenv, load_dotenv


@dataclass(frozen=True)
class Config:
    control_plane_url: str | None  # None means file-only mode, no polling
    dp_token: str | None
    bundle_public_key_b64: str
    cache_dir: Path
    staleness_policy: Literal["serve_and_warn", "refuse"]
    dev: bool = False  # set by the --dev flag on the entry point, gate dev-only behavior on this
    poll_interval_s: float = 30.0
    flush_interval_s: float = 5.0


class MissingConfigError(Exception):
    def __init__(self, env_name: str, file_key: str) -> None:
        super().__init__(f"missing setting: set {env_name} or data_plane.{file_key} in the config file")


def _file_section(name: str) -> dict[str, Any]:
    path = Path(os.environ.get("GW_CONFIG", "airllm.yml"))
    if not path.exists():
        return {}
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    section = doc.get(name)
    return section if isinstance(section, dict) else {}


def _resolve(value: object) -> str | None:
    text = str(value)
    if text.startswith("env:"):
        return os.environ.get(text.removeprefix("env:"))
    if text.startswith("file:"):
        ref = Path(text.removeprefix("file:"))
        return ref.read_text(encoding="utf-8").strip() if ref.exists() else None
    return text


def load_config() -> Config:
    load_dotenv(find_dotenv(usecwd=True))
    section = _file_section("data_plane")

    def setting(env_name: str, file_key: str, default: str | None = None) -> str | None:
        if env_name in os.environ:
            return os.environ[env_name]
        if section.get(file_key) is not None:
            resolved = _resolve(section[file_key])
            if resolved is not None:
                return resolved
        return default

    def required(env_name: str, file_key: str) -> str:
        value = setting(env_name, file_key)
        if not value:
            raise MissingConfigError(env_name, file_key)
        return value

    bundle_public_key = required("GW_BUNDLE_PUBLIC_KEY", "bundle_public_key")
    return Config(
        control_plane_url=setting("GW_CONTROL_PLANE_URL", "control_plane_url") or None,
        dp_token=setting("GW_DP_TOKEN", "dp_token") or None,
        bundle_public_key_b64=bundle_public_key,
        cache_dir=Path(setting("GW_CACHE_DIR", "cache_dir", "/var/cache/gateway") or "/var/cache/gateway"),
        staleness_policy="refuse" if setting("GW_STALENESS_POLICY", "staleness_policy", "serve_and_warn") == "refuse" else "serve_and_warn",
        dev=os.environ.get("GW_DEV") == "1",
        poll_interval_s=float(setting("GW_POLL_INTERVAL_S", "poll_interval_s", "30") or "30"),
        flush_interval_s=float(setting("GW_FLUSH_INTERVAL_S", "flush_interval_s", "5") or "5"),
    )
