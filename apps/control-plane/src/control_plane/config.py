from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml
from dotenv import find_dotenv, load_dotenv
from pydantic import BaseModel, ConfigDict, Field


class DatabaseConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str = "sqlite+aiosqlite:///airllm.db"


class AuthConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    token_signing_key: str  # base64 raw Ed25519, mints caller API tokens; rotates independently of the bundle key


class BundlePolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    signing_key: str  # base64 raw Ed25519, signs bundles
    staleness_bound_hours: float = 24.0

    @property
    def staleness_bound(self) -> timedelta:
        return timedelta(hours=self.staleness_bound_hours)


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    auth: AuthConfig
    bundle: BundlePolicy
    dev: bool = False  # set by the --dev flag on the entry point, gate dev-only behavior on this


def _file_section(name: str) -> dict[str, Any]:
    path = Path(os.environ.get("GW_CONFIG", "airllm.yml"))
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
    load_dotenv(find_dotenv(usecwd=True))
    raw = _resolve_refs(_file_section("control_plane"))
    assert isinstance(raw, dict)  # noqa: S101 _resolve_refs preserves the dict shape
    database = raw.get("database")
    url = database.get("url") if isinstance(database, dict) else None
    return str(url) if url else "sqlite+aiosqlite:///airllm.db"


def load_settings() -> Settings:
    load_dotenv(find_dotenv(usecwd=True))
    raw = _resolve_refs(_file_section("control_plane"))
    assert isinstance(raw, dict)  # noqa: S101 _resolve_refs preserves the dict shape
    return Settings.model_validate({**raw, "dev": os.environ.get("GW_DEV") == "1"})
