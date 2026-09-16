"""Ingress adapters: one explicit public path per caller dialect."""

from __future__ import annotations

import importlib
import inspect
import pkgutil

from data_plane.ingress.base import IngressAdapter


def _discover() -> dict[str, IngressAdapter]:
    registry: dict[str, IngressAdapter] = {}
    paths: set[str] = set()
    for mod_info in pkgutil.iter_modules(__path__):
        module = importlib.import_module(f"{__name__}.{mod_info.name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ != module.__name__ or not issubclass(obj, IngressAdapter) or inspect.isabstract(obj):
                continue
            if obj.dialect in registry:
                msg = f"duplicate ingress dialect {obj.dialect!r}"
                raise RuntimeError(msg)
            if obj.path in paths:
                msg = f"duplicate ingress path {obj.path!r}"
                raise RuntimeError(msg)
            registry[obj.dialect] = obj()
            paths.add(obj.path)
    return registry


REGISTRY = _discover()

__all__ = ["REGISTRY", "IngressAdapter"]
