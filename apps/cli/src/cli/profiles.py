from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

import tomli_w
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from airmux_runtime.files import write_private_text


class Profile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: Literal["instance", "org"]
    control_plane_url: str | None = None
    console_url: str | None = None
    gateway_url: str | None = None
    token: str | None = None
    org_id: str | None = None
    org_name: str | None = None
    workspace: str | None = None
    workspace_name: str | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        organization = self.org_id is not None and self.org_name is not None
        if self.scope == "org" and not organization:
            message = "an organization profile requires org_id and org_name"
            raise ValueError(message)
        if self.scope == "instance" and any((self.org_id, self.org_name, self.workspace, self.workspace_name)):
            message = "an instance profile cannot contain organization fields"
            raise ValueError(message)
        return self


class CliConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    active: str | None = None
    profiles: dict[str, Profile] = Field(default_factory=dict)


class InvalidConfigError(ValueError):
    pass


def config_path() -> Path:
    if override := os.environ.get("AIRMUX_CLI_CONFIG"):
        return Path(override)
    return Path.home() / ".airmux" / "config.toml"


def load_config() -> CliConfig:
    path = config_path()
    if path.exists():
        try:
            values = tomllib.loads(path.read_text(encoding="utf-8"))
            return CliConfig.model_validate(values)
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            message = f"Invalid configuration at {path}: the file is not valid TOML. Fix or move this file, then retry"
            raise InvalidConfigError(message) from None
        except ValidationError as error:
            issues = error.errors(include_url=False, include_context=False, include_input=False)
            details = "; ".join(f"{'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}" for issue in issues)
            message = f"Invalid configuration at {path}: {details}. Fix or move this file, then retry"
            raise InvalidConfigError(message) from None
    return CliConfig()


def save_config(config: CliConfig) -> None:
    write_private_text(config_path(), tomli_w.dumps(config.model_dump(mode="python", exclude_none=True)))


def active_profile(config: CliConfig) -> Profile | None:
    return config.profiles.get(config.active) if config.active is not None else None


def load_active_profile() -> Profile | None:
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
