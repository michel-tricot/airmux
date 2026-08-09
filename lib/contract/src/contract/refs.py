from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import find_dotenv, load_dotenv

_REF = re.compile(r"\$\{(env|file):([^}]+)\}")


class UnsupportedRefSchemeError(Exception):
    def __init__(self, scheme: str) -> None:
        super().__init__(f"unsupported ref scheme: {scheme}")


def resolve_ref(ref: str) -> str:
    scheme, _, rest = ref.partition(":")
    if scheme == "env":
        return os.environ[rest]
    if scheme == "file":
        return Path(rest).read_text(encoding="utf-8").strip()
    raise UnsupportedRefSchemeError(scheme)


def try_resolve_ref(ref: str) -> str | None:
    """The forgiving variant for config refs: missing values become None instead of raising."""
    scheme, _, rest = ref.partition(":")
    if scheme == "env":
        return os.environ.get(rest)
    if scheme == "file":
        source = Path(rest)
        return source.read_text(encoding="utf-8").strip() if source.exists() else None
    raise UnsupportedRefSchemeError(scheme)


def _interpolate(value: str) -> str | None:
    """Substitute every ${env:NAME} and ${file:PATH} placeholder; any missing ref voids the whole string."""
    refs = {match.group(0): try_resolve_ref(f"{match.group(1)}:{match.group(2)}") for match in _REF.finditer(value)}
    if not refs:
        return value
    resolved = {placeholder: text for placeholder, text in refs.items() if text is not None}
    if len(resolved) < len(refs):
        return None
    return _REF.sub(lambda match: resolved[match.group(0)], value)


def resolve_refs(node: object) -> object:
    if isinstance(node, dict):
        return {key: resolve_refs(value) for key, value in node.items()}
    if isinstance(node, list):
        return [resolve_refs(value) for value in node]
    if isinstance(node, str):
        if node.startswith(("env:", "file:")):
            return try_resolve_ref(node)
        return _interpolate(node)
    return node


def load_config_section(name: str, config_path: str | Path | None = None) -> dict[str, Any]:
    """One plane's section of the shared config file, refs resolved; the path falls back to GW_CONFIG."""
    load_dotenv(find_dotenv(usecwd=True))
    path = Path(config_path) if config_path else Path(os.environ.get("GW_CONFIG", "airllm.yml"))
    if not path.exists():
        return {}
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    section = doc.get(name)
    if not isinstance(section, dict):
        return {}
    return {str(key): resolve_refs(value) for key, value in section.items()}
