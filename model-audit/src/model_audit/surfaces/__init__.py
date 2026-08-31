from __future__ import annotations

import importlib
import inspect
import pkgutil
from functools import cache

from model_audit.surfaces.base import SurfaceCodec


@cache
def discover() -> dict[str, SurfaceCodec]:
    codecs = {}
    for module_info in pkgutil.iter_modules(__path__):
        if module_info.name == "base":
            continue
        module = importlib.import_module(f"{__name__}.{module_info.name}")
        for _, codec_type in inspect.getmembers(module, inspect.isclass):
            if codec_type.__module__ != module.__name__ or not issubclass(codec_type, SurfaceCodec) or inspect.isabstract(codec_type):
                continue
            codec = codec_type()
            if codec.id in codecs:
                message = f"duplicate surface codec {codec.id!r}"
                raise RuntimeError(message)
            codecs[codec.id] = codec
    return dict(sorted(codecs.items(), key=lambda item: (item[1].priority, item[0])))


def by_endpoint(endpoint: str) -> SurfaceCodec:
    codec = next((codec for codec in discover().values() if codec.endpoint == endpoint), None)
    if codec is None:
        message = f"no surface codec owns endpoint {endpoint}"
        raise ValueError(message)
    return codec


__all__ = ["SurfaceCodec", "by_endpoint", "discover"]
