from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

import tomli_w
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from contract.secrets.file import write_private_text


class _Profile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    control_plane_url: str | None = None
    console_url: str | None = None
    gateway_url: str | None = None
    token: str | None = None


class InstanceProfile(_Profile):
    scope: Literal["instance"] = "instance"


class OrgProfile(_Profile):
    scope: Literal["org"] = "org"
    org_id: str
    org_name: str
    workspace: str | None = None
    workspace_name: str | None = None


Profile = Annotated[InstanceProfile | OrgProfile, Field(discriminator="scope")]
PROFILE_ADAPTER = TypeAdapter(Profile)


class NamedInstanceProfile(InstanceProfile):
    name: str


class NamedOrgProfile(OrgProfile):
    name: str


NamedProfile = Annotated[NamedInstanceProfile | NamedOrgProfile, Field(discriminator="scope")]
NAMED_PROFILE_ADAPTER = TypeAdapter(NamedProfile)


def profile_from(value: object) -> Profile:
    return PROFILE_ADAPTER.validate_python(value)


class CliConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

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
        return NAMED_PROFILE_ADAPTER.validate_python({"name": name, **profile.model_dump(mode="python")})
    return None


def load_active_profile() -> NamedProfile | None:
    return active_profile(load_config())


def upsert_profile(name: str, profile: Profile, *, activate: bool = True) -> None:
    config = load_config()
    profiles = {**config.profiles, name: profile}
    save_config(config.model_copy(update={"profiles": profiles, "active": name if activate else config.active}))


def upsert_url_profile(name: str, profile: Profile, *, activate: bool = True) -> str:
    config = load_config()
    profiles = config.profiles
    control_plane_url = (profile.control_plane_url or "").rstrip("/")
    matching = next(
        (
            profile_name
            for profile_name, candidate_profile in profiles.items()
            if (name == profile_name or (candidate_profile.scope == "org" and name == candidate_profile.org_name))
            and (candidate_profile.control_plane_url or "").rstrip("/") == control_plane_url
            and candidate_profile.scope == profile.scope
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
