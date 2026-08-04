from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from data_plane.auth import index_keys

if TYPE_CHECKING:
    from contract import BundleV1, KeyEntry

logger = logging.getLogger("data_plane")


@dataclass(frozen=True)
class BundleSnapshot:
    """Everything a request needs from the bundle, swapped as one reference.

    Handlers grab the snapshot once; a mid-request swap can never tear the
    key index away from the bundle it was built from.
    """

    bundle: BundleV1
    key_index: dict[str, KeyEntry]
    revocations: frozenset[str]


class BundleHolder:
    def __init__(self) -> None:
        self.snapshot: BundleSnapshot | None = None

    def admit(self, bundle: BundleV1, staleness_policy: Literal["serve_and_warn", "refuse"], source: str) -> bool:
        """The one place bundles are accepted: staleness policy, index build, atomic swap."""
        expired = bundle.expires_at <= datetime.now(tz=UTC)
        if expired and staleness_policy == "refuse":
            logger.error("%s bundle %s expired at %s and policy is refuse, not loading", source, bundle.bundle_id, bundle.expires_at)
            return False
        if expired:
            logger.warning("%s bundle %s expired at %s, serving stale per policy", source, bundle.bundle_id, bundle.expires_at)
        self.snapshot = BundleSnapshot(bundle=bundle, key_index=index_keys(bundle), revocations=frozenset(bundle.revocations))
        logger.info("adopted %s bundle %s issued %s", source, bundle.bundle_id, bundle.issued_at)
        return True
