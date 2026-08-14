from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from data_plane.auth import index_keys
from data_plane.credentials import index_credentials
from data_plane.profiles import index_profiles

if TYPE_CHECKING:
    from contract import BundleV1, KeyEntry
    from data_plane.credentials import CredentialIndex
    from data_plane.profiles import CompiledProfile

logger = logging.getLogger("data_plane")


@dataclass(frozen=True)
class BundleSnapshot:
    """Everything a request needs from the bundle, swapped as one reference.

    Handlers grab the snapshot once; a mid-request swap can never tear the
    key index away from the bundle it was built from. The indexes are built here
    rather than per request, so the request path only does lookups.
    """

    bundle: BundleV1
    key_index: dict[str, KeyEntry]
    credential_index: CredentialIndex
    profile_index: dict[str, CompiledProfile]


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
        self.snapshot = BundleSnapshot(
            bundle=bundle, key_index=index_keys(bundle), credential_index=index_credentials(bundle), profile_index=index_profiles(bundle)
        )
        logger.info("adopted %s bundle %s issued %s", source, bundle.bundle_id, bundle.issued_at)
        return True
