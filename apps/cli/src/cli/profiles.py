from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import tomli_w
from pydantic import BaseModel, ConfigDict, Field, model_validator

from contract.secrets.file import write_private_text


class Profile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    control_plane_url: str | None = None
    console_url: str | None = None
    gateway_url: str | None = None
    token: str | None = None
    scope: Literal["instance", "org"] | None = None
    org_id: str | None = None
    org_name: str | None = None
    personal_org_id: str | None = None
    workspace: str | None = None
    workspace_id: str | None = None
    workspace_name: str | None = None

    @model_validator(mode="before")
    @classmethod
    def infer_legacy_scope(cls, value: object) -> object:
        if isinstance(value, Mapping) and "scope" not in value and value.get("org_id"):
            return {**value, "scope": "org"}
        return value


class NamedProfile(Profile):
    name: str


class CliConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    active: str | None = None
    profiles: dict[str, Profile] = Field(default_factory=dict)


def config_path() -> Path:
    if override := os.environ.get("GW_CLI_CONFIG"):
        return Path(override)
    return Path.home() / ".airllm" / "config.toml"


def load_config() -> CliConfig:
    path = config_path()
    if path.exists():
        return CliConfig.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))
    return CliConfig()


def save_config(config: CliConfig) -> None:
    write_private_text(config_path(), tomli_w.dumps(config.model_dump(mode="python", exclude_none=True)))


def active_profile(config: CliConfig) -> NamedProfile | None:
    name = config.active
    if name is not None and (profile := config.profiles.get(name)) is not None:
        return NamedProfile.model_validate({"name": name, **profile.model_dump(mode="python")})
    return None


def load_active_profile() -> NamedProfile | None:
    return active_profile(load_config())


def upsert_profile(name: str, profile: Profile, *, activate: bool = True) -> None:
    config = load_config()
    profiles = {**config.profiles, name: profile}
    save_config(config.model_copy(update={"profiles": profiles, "active": name if activate else config.active}))


def _profile_scope(profile: Profile) -> Literal["instance", "org"] | None:
    return profile.scope


def upsert_url_profile(name: str, profile: Profile, *, activate: bool = True) -> str:
    config = load_config()
    profiles = config.profiles
    control_plane_url = (profile.control_plane_url or "").rstrip("/")
    matching = next(
        (
            profile_name
            for profile_name, candidate_profile in profiles.items()
            if name in (profile_name, candidate_profile.org_name)
            and (candidate_profile.control_plane_url or "").rstrip("/") == control_plane_url
            and _profile_scope(candidate_profile) == _profile_scope(profile)
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
    updated_profiles = {**profiles, profile_name: profile}
    save_config(config.model_copy(update={"profiles": updated_profiles, "active": profile_name if activate else config.active}))
    return profile_name


def set_active(name: str) -> None:
    config = load_config()
    if name not in config.profiles:
        raise KeyError(name)
    save_config(config.model_copy(update={"active": name}))


def remove_profile(name: str) -> None:
    config = load_config()
    profiles = dict(config.profiles)
    if name not in profiles:
        raise KeyError(name)
    del profiles[name]
    active = config.active
    next_active = next(iter(profiles), None) if active == name else active
    save_config(config.model_copy(update={"profiles": profiles, "active": next_active}))


DEFAULT_CONSOLE_URL = "http://localhost:5000"
