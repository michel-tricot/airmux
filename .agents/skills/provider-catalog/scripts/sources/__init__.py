"""Per-provider model catalog sources. See base.py for how to add one."""

from .base import ModelSource, registry

__all__ = ["ModelSource", "registry"]
