from __future__ import annotations

import logging
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Self

from data_plane.credentials import index_credentials
from data_plane.profiles import index_profiles

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from uuid import UUID

    from contract import BundleV1, KeyEntry, ModelEntry, ProviderEntry
    from data_plane.credentials import CredentialIndex
    from data_plane.profiles import CompiledProfile

logger = logging.getLogger("data_plane")


class DuplicateOrgBundleError(ValueError):
    pass


class DuplicateInferenceTokenError(ValueError):
    pass


@dataclass(frozen=True)
class BundleSnapshot:
    """Everything a request needs from one organization's bundle.

    The indexes are built here rather than per request, so the request path only
    does lookups.
    """

    bundle: BundleV1
    model_index: dict[str, ModelEntry]
    provider_index: dict[str, ProviderEntry]
    credential_index: CredentialIndex
    profile_index: dict[str, CompiledProfile]

    @classmethod
    def from_bundle(cls, bundle: BundleV1) -> Self:
        return cls(
            bundle=bundle,
            model_index={model.model_id: model for model in bundle.catalog.models},
            provider_index={provider.provider_id: provider for provider in bundle.catalog.providers},
            credential_index=index_credentials(bundle),
            profile_index=index_profiles(bundle),
        )


@dataclass(frozen=True)
class BundleSet:
    snapshots: Mapping[UUID, BundleSnapshot]
    key_index: Mapping[str, KeyEntry]

    @classmethod
    def from_bundles(cls, bundles: Iterable[BundleV1]) -> Self:
        bundle_list = tuple(bundles)
        snapshots = {bundle.org_id: BundleSnapshot.from_bundle(bundle) for bundle in bundle_list}
        if len(snapshots) != len(bundle_list):
            raise DuplicateOrgBundleError
        keys = [(key.token_hash, key) for bundle in bundle_list for key in bundle.keys]
        key_index = dict(keys)
        if len(key_index) != len(keys):
            raise DuplicateInferenceTokenError
        return cls(snapshots=MappingProxyType(snapshots), key_index=MappingProxyType(key_index))


class BundleHolder:
    def __init__(self) -> None:
        self._current = BundleSet.from_bundles(())

    @property
    def current(self) -> BundleSet:
        return self._current

    def swap(self, current: BundleSet, source: str) -> None:
        self._current = current
        logger.info("adopted %s bundle manifest with %d organizations", source, len(current.snapshots))
