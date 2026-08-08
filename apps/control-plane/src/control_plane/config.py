from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml
from dotenv import find_dotenv, load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from contract import Ed25519PrivateKeyB64


class DatabaseConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str = "postgresql+asyncpg://airllm:airllm@127.0.0.1:5432/airllm"


class BundlePolicy(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    signing_key: Ed25519PrivateKeyB64  # parsed once from base64 at load; signs bundles
    staleness_bound_hours: float = 24.0

    @property
    def staleness_bound(self) -> timedelta:
        return timedelta(hours=self.staleness_bound_hours)


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    bundle: BundlePolicy
    webapp_url: str = "http://127.0.0.1:5173"  # where the webapp lives; device-flow verification URLs are built from it
    dev: bool = False  # set by the --dev flag on the entry point, gate dev-only behavior on this


def _file_section(name: str, config_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(config_path) if config_path else Path(os.environ.get("GW_CONFIG", "airllm.yml"))
    if not path.exists():
        return {}
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    section = doc.get(name)
    return section if isinstance(section, dict) else {}


def _resolve_refs(node: object) -> object:
    if isinstance(node, dict):
        return {k: _resolve_refs(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_refs(v) for v in node]
    if isinstance(node, str):
        if node.startswith("env:"):
            return os.environ.get(node.removeprefix("env:"))
        if node.startswith("file:"):
            ref = Path(node.removeprefix("file:"))
            return ref.read_text(encoding="utf-8").strip() if ref.exists() else None
    return node


def database_url() -> str:
    """The database section alone, for contexts (migrate, alembic env) that have no signing key and cannot build full Settings."""
    load_dotenv(find_dotenv(usecwd=True))
    raw = _resolve_refs(_file_section("control_plane"))
    assert isinstance(raw, dict)  # noqa: S101 _resolve_refs preserves the dict shape
    return DatabaseConfig.model_validate(raw.get("database") or {}).url


def load_settings(config_path: str | Path | None = None) -> Settings:
    """Load settings from an explicit config path, falling back to GW_CONFIG for the serve/migrate contexts that pass it via env."""
    load_dotenv(find_dotenv(usecwd=True))
    raw = _resolve_refs(_file_section("control_plane", config_path))
    assert isinstance(raw, dict)  # noqa: S101 _resolve_refs preserves the dict shape
    return Settings.model_validate({**raw, "dev": os.environ.get("GW_DEV") == "1"})
