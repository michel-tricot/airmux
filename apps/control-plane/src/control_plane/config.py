from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml
from dotenv import find_dotenv, load_dotenv


@dataclass(frozen=True)
class Settings:
    database_url: str
    admin_token: str
    dp_token: str
    signing_key_b64: str
    signing_key_id: str
    staleness_bound: timedelta
    dev: bool = False  # set by the --dev flag on the entry point, gate dev-only behavior on this


class MissingConfigError(Exception):
    def __init__(self, env_name: str, file_key: str) -> None:
        super().__init__(f"missing setting: set {env_name} or control_plane.{file_key} in the config file")


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


def _setting(section: dict[str, Any], env_name: str, file_key: str, default: str | None = None) -> str | None:
    if env_name in os.environ:
        return os.environ[env_name]
    if section.get(file_key) is not None:
        resolved = _resolve(section[file_key])
        if resolved is not None:
            return resolved
    return default


def _required(section: dict[str, Any], env_name: str, file_key: str) -> str:
    value = _setting(section, env_name, file_key)
    if not value:
        raise MissingConfigError(env_name, file_key)
    return value


def database_url() -> str:
    load_dotenv(find_dotenv(usecwd=True))
    section = _file_section("control_plane")
    return _setting(section, "GW_DATABASE_URL", "database_url", "sqlite+aiosqlite:///airllm.db") or "sqlite+aiosqlite:///airllm.db"


def load_settings() -> Settings:
    load_dotenv(find_dotenv(usecwd=True))
    section = _file_section("control_plane")
    return Settings(
        database_url=database_url(),
        admin_token=_required(section, "GW_ADMIN_TOKEN", "admin_token"),
        dp_token=_required(section, "GW_DP_TOKEN", "dp_token"),
        signing_key_b64=_required(section, "GW_SIGNING_KEY", "signing_key"),
        signing_key_id=_setting(section, "GW_SIGNING_KEY_ID", "signing_key_id", "k1") or "k1",
        staleness_bound=timedelta(hours=float(_setting(section, "GW_STALENESS_BOUND_HOURS", "staleness_bound_hours", "24") or "24")),
        dev=os.environ.get("GW_DEV") == "1",
    )
