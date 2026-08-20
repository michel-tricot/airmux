from __future__ import annotations

import importlib
import inspect
import pkgutil

from provider_parity.drivers.base import SDKDriver


def discover() -> dict[str, SDKDriver]:
    drivers: dict[str, SDKDriver] = {}
    for module_info in pkgutil.iter_modules(__path__):
        module = importlib.import_module(f"{__name__}.{module_info.name}")
        for _, driver_type in inspect.getmembers(module, inspect.isclass):
            if driver_type.__module__ != module.__name__ or not issubclass(driver_type, SDKDriver) or inspect.isabstract(driver_type):
                continue
            driver = driver_type()
            if driver.id in drivers:
                message = f"duplicate SDK driver {driver.id!r}"
                raise RuntimeError(message)
            drivers[driver.id] = driver
    return drivers


def supported_endpoints() -> dict[str, frozenset[str]]:
    return {driver_id: driver.endpoints for driver_id, driver in discover().items()}


__all__ = ["SDKDriver", "discover", "supported_endpoints"]
