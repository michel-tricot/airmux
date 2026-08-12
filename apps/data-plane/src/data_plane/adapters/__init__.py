from __future__ import annotations

import importlib
import inspect
import pkgutil

from data_plane.adapters.base import ProviderAdapter


def _discover() -> dict[str, type[ProviderAdapter]]:
    registry: dict[str, type[ProviderAdapter]] = {}
    for mod_info in pkgutil.iter_modules(__path__):
        module = importlib.import_module(f"{__name__}.{mod_info.name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, ProviderAdapter) and not inspect.isabstract(obj):
                registry[obj.kind] = obj
    return registry


REGISTRY = _discover()

__all__ = ["REGISTRY", "ProviderAdapter"]
