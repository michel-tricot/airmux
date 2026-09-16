from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import AfterValidator, Field, ValidationInfo

_REFERENCE = re.compile(r"^\$\{(env|file):(.+)\}$")
_DEFAULT_SEPARATOR = ":-"


class UnsupportedRefSchemeError(ValueError):
    def __init__(self, scheme: str) -> None:
        super().__init__(f"unsupported configuration reference scheme: {scheme}")


class MissingConfigReferenceError(ValueError):
    def __init__(self, scheme: str, target: str) -> None:
        super().__init__(f"configuration references missing {scheme} value: {target}")


class InvalidConfigReferenceError(ValueError):
    def __init__(self) -> None:
        super().__init__("configuration references must occupy the whole YAML value and use the env or file scheme")


@dataclass(frozen=True)
class ConfigContext:
    base_dir: Path


def _resolve_path(path: Path, info: ValidationInfo) -> Path:
    if isinstance(info.context, ConfigContext):
        return info.context.base_dir / path
    return path


ConfigPath = Annotated[Path, AfterValidator(_resolve_path), Field(validate_default=True)]


def load_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _split_default(value: str) -> tuple[str, str | None]:
    target, separator, fallback = value.partition(_DEFAULT_SEPARATOR)
    return (target, fallback) if separator else (target, None)


def resolve_ref(ref: str, *, base_dir: Path = Path()) -> str:
    scheme, separator, value = ref.partition(":")
    if not separator or scheme not in {"env", "file"}:
        raise UnsupportedRefSchemeError(scheme)
    target, fallback = _split_default(value)
    if scheme == "env":
        resolved = os.environ.get(target, fallback)
    else:
        source = base_dir / target
        resolved = source.read_text(encoding="utf-8").strip() if source.is_file() else fallback
    if resolved is None:
        raise MissingConfigReferenceError(scheme, target)
    return resolved


def resolve_refs(node: object, *, base_dir: Path = Path()) -> object:
    if isinstance(node, dict):
        return {key: resolve_refs(value, base_dir=base_dir) for key, value in node.items()}
    if isinstance(node, list):
        return [resolve_refs(value, base_dir=base_dir) for value in node]
    if isinstance(node, str):
        if match := _REFERENCE.fullmatch(node):
            return resolve_ref(f"{match.group(1)}:{match.group(2)}", base_dir=base_dir)
        if "${" in node:
            raise InvalidConfigReferenceError
    return node


def load_config_section(name: str, config_path: str | Path) -> dict[str, object]:
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    document = load_yaml(path)
    if not isinstance(document, dict):
        message = f"{path} must contain a {name} section"
        raise TypeError(message)
    declared = document.get(name)
    if not isinstance(declared, dict):
        message = f"{path} must contain a {name} section"
        raise TypeError(message)
    section = resolve_refs(declared, base_dir=path.parent)
    if not isinstance(section, dict):
        message = f"{path} must contain a {name} mapping"
        raise TypeError(message)
    return {str(key): value for key, value in section.items()}
