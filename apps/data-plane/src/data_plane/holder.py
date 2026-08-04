from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gw_contract import BundleV1, KeyEntry


class BundleHolder:
    def __init__(self) -> None:
        self.current: BundleV1 | None = None
        self.key_index: dict[str, KeyEntry] = {}
        self.revocations: frozenset[str] = frozenset()

    def swap(self, bundle: BundleV1, key_index: dict[str, KeyEntry]) -> None:
        self.key_index = key_index
        self.revocations = frozenset(bundle.revocations)
        self.current = bundle
