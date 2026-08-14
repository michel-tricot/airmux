from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import find_dotenv, load_dotenv

_REF = re.compile(r"\$\{(env|file):([^}]+)\}")
_VAR = re.compile(r"\$\{var:([^}]+)\}")


class UnsupportedRefSchemeError(Exception):
    def __init__(self, scheme: str) -> None:
        super().__init__(f"unsupported ref scheme: {scheme}")


class UnknownVarError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"config references ${{var:{name}}} but the vars block does not define it")


DEFAULT_SEPARATOR = ":-"


def _split_default(rest: str) -> tuple[str, str | None]:
    """Separate a ref's target from the default written after :-, shell style.

    The separator being present is what makes a default, so ${env:NAME:-} is an empty value rather
    than a missing one. A target that legitimately contains :- cannot take a default, which no
    environment variable name and no path here does.
    """
    target, separator, fallback = rest.partition(DEFAULT_SEPARATOR)
    return (target, fallback) if separator else (target, None)


def resolve_ref(ref: str) -> str:
    scheme, _, rest = ref.partition(":")
    target, fallback = _split_default(rest)
    if scheme == "env":
        return os.environ[target] if fallback is None else os.environ.get(target, fallback)
    if scheme == "file":
        source = Path(target)
        if fallback is not None and not source.exists():
            return fallback
        return source.read_text(encoding="utf-8").strip()
    raise UnsupportedRefSchemeError(scheme)


def try_resolve_ref(ref: str) -> str | None:
    """The forgiving variant for config refs: missing values become None instead of raising, unless the ref carries a default."""
    scheme, _, rest = ref.partition(":")
    target, fallback = _split_default(rest)
    if scheme == "env":
        return os.environ.get(target, fallback)
    if scheme == "file":
        source = Path(target)
        return source.read_text(encoding="utf-8").strip() if source.exists() else fallback
    raise UnsupportedRefSchemeError(scheme)


def _interpolate(value: str) -> str | None:
    """Substitute every ${env:NAME} and ${file:PATH} placeholder; a missing ref with no :- default voids the whole string."""
    refs = {match.group(0): try_resolve_ref(f"{match.group(1)}:{match.group(2)}") for match in _REF.finditer(value)}
    if not refs:
        return value
    resolved = {placeholder: text for placeholder, text in refs.items() if text is not None}
    if len(resolved) < len(refs):
        return None
    return _REF.sub(lambda match: resolved[match.group(0)], value)


def _substitute_vars(value: str, variables: dict[str, str]) -> str:
    """The pass before ref resolution: ${var:NAME} is plain text substitution from the vars
    block, so a var can sit inside a ref, as in ${file:${var:dir}/signing.key}. Vars hold
    values, never logic; an unknown name fails loudly."""

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in variables:
            raise UnknownVarError(name)
        return variables[name]

    return _VAR.sub(replace, value)


def resolve_refs(node: object, variables: dict[str, str] | None = None) -> object:
    if isinstance(node, dict):
        return {key: resolve_refs(value, variables) for key, value in node.items()}
    if isinstance(node, list):
        return [resolve_refs(value, variables) for value in node]
    if isinstance(node, str):
        if variables is not None:
            node = _substitute_vars(node, variables)
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
    declared = doc.get("vars")
    variables = {str(key): str(value) for key, value in declared.items()} if isinstance(declared, dict) else {}
    section = doc.get(name)
    if not isinstance(section, dict):
        return {}
    return {str(key): resolve_refs(value, variables) for key, value in section.items()}
