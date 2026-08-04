from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from data_plane.canonical import CanonicalRequest
    from gw_contract import BundleV1, KeyEntry, ModelEntry, ProviderEntry


@dataclass(frozen=True)
class Allow:
    model: ModelEntry
    provider: ProviderEntry


@dataclass(frozen=True)
class Deny:
    reason: str
    status: int


type Decision = Allow | Deny


def evaluate(req: CanonicalRequest, key: KeyEntry, bundle: BundleV1, now: datetime) -> Decision:
    """Pure and synchronous: no async, no network, no I/O, no datetime.now(). Under 100 lines."""
    raise NotImplementedError
