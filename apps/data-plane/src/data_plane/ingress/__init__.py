"""Ingress adapters: one module per caller dialect, discovered like their egress counterparts.

resolve() owns discrimination end to end: the explicit override header wins, then each
registered dialect's claims() in registry order, then canonical as the unclaimed default. A
text-only body is shape-identical across chat dialects, which is why claims() leans on client
fingerprints and unambiguous markers rather than trying to be total."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import TYPE_CHECKING, Any

from data_plane.ingress.base import DIALECT_HEADER, IngressAdapter

if TYPE_CHECKING:
    from starlette.datastructures import Headers

CANONICAL = "canonical"


class UnknownDialectError(ValueError):
    pass


def _discover() -> dict[str, IngressAdapter]:
    registry: dict[str, IngressAdapter] = {}
    for mod_info in pkgutil.iter_modules(__path__):
        module = importlib.import_module(f"{__name__}.{mod_info.name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ != module.__name__ or not issubclass(obj, IngressAdapter) or inspect.isabstract(obj):
                continue
            if obj.dialect in registry:
                msg = f"duplicate ingress dialect {obj.dialect!r}"
                raise RuntimeError(msg)
            registry[obj.dialect] = obj()
    return registry


REGISTRY = _discover()


def resolve(headers: Headers, body: dict[str, Any]) -> IngressAdapter:
    override = headers.get(DIALECT_HEADER, "").lower()
    if override:
        if override not in REGISTRY:
            raise UnknownDialectError(override)
        return REGISTRY[override]
    for dialect, adapter in REGISTRY.items():
        if dialect != CANONICAL and adapter.claims(headers, body):
            return adapter
    return REGISTRY[CANONICAL]


__all__ = ["REGISTRY", "IngressAdapter", "UnknownDialectError", "resolve"]
