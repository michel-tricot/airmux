from __future__ import annotations

import logging
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Self

from data_plane.credentials import index_credentials
from data_plane.profiles import index_profiles

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from datetime import datetime
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
    """Everything a request needs from the bundle, swapped as one reference.

    Handlers grab the snapshot once; a mid-request swap can never tear the
    key index away from the bundle it was built from. The indexes are built here
    rather than per request, so the request path only does lookups.
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
class BundleRoute:
    key: KeyEntry
    snapshot: BundleSnapshot

    @property
    def expires_at(self) -> datetime | None:
        return self.key.expires_at


@dataclass(frozen=True)
class BundleSet:
    snapshots: Mapping[UUID, BundleSnapshot]
    key_index: Mapping[str, BundleRoute]

    @classmethod
    def from_bundles(cls, bundles: Iterable[BundleV1]) -> Self:
        bundle_list = tuple(bundles)
        snapshots = {bundle.org_id: BundleSnapshot.from_bundle(bundle) for bundle in bundle_list}
        if len(snapshots) != len(bundle_list):
            raise DuplicateOrgBundleError
        routes = [(key.token_hash, BundleRoute(key=key, snapshot=snapshots[bundle.org_id])) for bundle in bundle_list for key in bundle.keys]
        key_index = dict(routes)
        if len(key_index) != len(routes):
            raise DuplicateInferenceTokenError
        return cls(snapshots=MappingProxyType(snapshots), key_index=MappingProxyType(key_index))


class BundleHolder:
    def __init__(self) -> None:
        self._current = BundleSet.from_bundles(())

    @property
    def snapshots(self) -> Mapping[UUID, BundleSnapshot]:
        return self._current.snapshots

    @property
    def key_index(self) -> Mapping[str, BundleRoute]:
        return self._current.key_index

    def admit(self, bundle: BundleV1, source: str) -> None:
        bundles = [snapshot.bundle for org_id, snapshot in self.snapshots.items() if org_id != bundle.org_id]
        self.replace((*bundles, bundle), source)

    def replace(self, bundles: Iterable[BundleV1], source: str) -> None:
        self.publish(self.prepare(bundles), source)

    def prepare(self, bundles: Iterable[BundleV1]) -> BundleSet:
        return BundleSet.from_bundles(bundles)

    def publish(self, current: BundleSet, source: str) -> None:
        self._current = current
        logger.info("adopted %s bundle manifest with %d organizations", source, len(current.snapshots))
