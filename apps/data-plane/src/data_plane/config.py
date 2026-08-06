from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import find_dotenv, load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from contract import Ed25519PublicKeyB64
from data_plane.secrets import try_resolve


class ControlPlaneLink(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str | None = None  # None means file-only mode, no polling
    token: str | None = None
    heartbeat_interval_s: float = 30.0


class BundleConfig(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    public_key: Ed25519PublicKeyB64  # parsed once from base64 at load; verifies bundle signatures
    org: str | None = None  # which org's bundle this data plane serves; None takes the newest across orgs
    cache_dir: Path = Path("/var/cache/gateway")
    staleness_policy: Literal["serve_and_warn", "refuse"] = "serve_and_warn"
    poll_interval_s: float = 30.0


class AuthConfig(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    token_public_key: Ed25519PublicKeyB64  # parsed once from base64 at load; verifies caller API tokens, distinct from the bundle key


class EventsConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    flush_interval_s: float = 5.0
    backend: Literal["sqlite", "devnull"] = "sqlite"  # how usage events are collected; devnull discards them


class Config(BaseModel):
    model_config = ConfigDict(frozen=True)

    control_plane: ControlPlaneLink = Field(default_factory=ControlPlaneLink)
    bundle: BundleConfig
    auth: AuthConfig
    events: EventsConfig = Field(default_factory=EventsConfig)
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
    if isinstance(node, str) and node.startswith(("env:", "file:")):
        return try_resolve(node)
    return node


def load_config() -> Config:
    load_dotenv(find_dotenv(usecwd=True))
    raw = _resolve_refs(_file_section("data_plane"))
    assert isinstance(raw, dict)  # noqa: S101 _resolve_refs preserves the dict shape
    return Config.model_validate({**raw, "dev": os.environ.get("GW_DEV") == "1"})
