from __future__ import annotations

import logging
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, Self

from airmux_runtime.observability import log_event
from contract.policies import Budget
from data_plane.auth import index_keys
from data_plane.credentials import index_credentials
from data_plane.egress import REGISTRY
from data_plane.policies import PolicyIndex, compile_policies
from data_plane.profiles import index_profiles

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping
    from uuid import UUID

    from contract import BundleV1, KeyEntry, ModelEntry, ProviderEntry
    from data_plane.credentials import CredentialIndex
    from data_plane.metrics import DataPlaneMetrics
    from data_plane.profiles import CompiledProfile

logger = logging.getLogger("data_plane")


@dataclass(frozen=True)
class BundleSnapshot:
    """Everything a request needs from one organization's bundle.

    The indexes are built here rather than per request, so the request path only
    does lookups.
    """

    bundle: BundleV1
    model_index: Mapping[str, ModelEntry]
    provider_index: Mapping[str, ProviderEntry]
    credential_index: CredentialIndex
    profile_index: Mapping[str, CompiledProfile]
    provider_param_aliases: frozenset[str]
    policy_index: PolicyIndex
    budget_index: PolicyIndex

    @classmethod
    def from_bundle(cls, bundle: BundleV1) -> Self:
        provider_index = _unique_index(bundle.catalog.providers, lambda provider: provider.provider_id, "provider")
        model_index = _unique_index(bundle.catalog.models, lambda model: model.model_id, "model")
        profile_index = index_profiles(bundle)
        _admit_keys(bundle)
        _admit_providers(provider_index)
        _admit_models(model_index, provider_index)
        _admit_credentials(bundle, provider_index)
        policy_index = compile_policies(bundle.policies)
        return cls(
            bundle=bundle,
            model_index=MappingProxyType(model_index),
            provider_index=MappingProxyType(provider_index),
            credential_index=MappingProxyType(index_credentials(bundle)),
            profile_index=MappingProxyType(profile_index),
            provider_param_aliases=frozenset(spelling for profile in profile_index.values() for spelling in profile.respelled),
            policy_index=policy_index,
            budget_index=MappingProxyType(
                {
                    workspace_id: tuple(rule for rule in rules if isinstance(rule.definition.action, Budget))
                    for workspace_id, rules in policy_index.items()
                }
            ),
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
            message = "bundle set contains more than one bundle for an organization"
            raise ValueError(message)
        key_indexes = tuple(index_keys(bundle) for bundle in bundle_list)
        key_count = sum(len(bundle.keys) for bundle in bundle_list)
        key_index = {token_hash: key for index in key_indexes for token_hash, key in index.items()}
        if len(key_index) != key_count:
            message = "inference token hash appears in more than one bundle"
            raise ValueError(message)
        return cls(snapshots=MappingProxyType(snapshots), key_index=MappingProxyType(key_index))


class BundleHolder:
    def __init__(self, metrics: DataPlaneMetrics, *, supports_budgets: bool = True) -> None:
        self._supports_budgets = supports_budgets
        self._current = BundleSet.from_bundles(())
        self._metrics = metrics

    @property
    def current(self) -> BundleSet:
        return self._current

    def swap(self, current: BundleSet, source: str) -> None:
        if not self._supports_budgets and any(
            isinstance(rule.action, Budget)
            for snapshot in current.snapshots.values()
            for policy in snapshot.bundle.policies
            for rule in policy.definition.rules
        ):
            message = "Budgets require remote bundles and event export to the same control plane"
            raise ValueError(message)
        self._current = current
        self._metrics.observe_bundle_adopted(len(current.snapshots))
        logger.info("adopted %s bundle manifest with %d organizations", source, len(current.snapshots))

    def reject_manifest(self) -> None:
        self._metrics.observe_bundle_poll("rejected")
        log_event(logger, logging.ERROR, "bundle_manifest_rejected", outcome="rejected")

    def record_poll(self, outcome: Literal["unchanged", "failed"]) -> None:
        self._metrics.observe_bundle_poll(outcome)


def _unique_index[T](entries: Iterable[T], key: Callable[[T], str], label: str) -> dict[str, T]:
    values = tuple(entries)
    index = {key(entry): entry for entry in values}
    if len(index) != len(values):
        message = f"duplicate {label} id"
        raise ValueError(message)
    return index


def _admit_keys(bundle: BundleV1) -> None:
    for key in bundle.keys:
        if key.org_id != bundle.org_id:
            message = f"key {key.key_id} belongs to another organization"
            raise ValueError(message)


def _admit_providers(provider_index: Mapping[str, ProviderEntry]) -> None:
    for provider in provider_index.values():
        if provider.kind not in REGISTRY:
            message = f"provider {provider.provider_id} names unknown egress adapter {provider.kind}"
            raise ValueError(message)


def _admit_models(model_index: Mapping[str, ModelEntry], provider_index: Mapping[str, ProviderEntry]) -> None:
    for model in model_index.values():
        provider = provider_index.get(model.provider_id)
        if provider is None:
            message = f"model {model.model_id} names unknown provider {model.provider_id}"
            raise ValueError(message)
        egress_kind = model.egress_kind or provider.kind
        if egress_kind not in REGISTRY:
            message = f"model {model.model_id} names unknown egress adapter {egress_kind}"
            raise ValueError(message)
        if egress_kind == "anthropic" and model.max_output_tokens is None:
            message = f"anthropic model {model.model_id} requires max_output_tokens in the bundle"
            raise ValueError(message)


def _admit_credentials(bundle: BundleV1, provider_index: Mapping[str, ProviderEntry]) -> None:
    secret_ids = set()
    for entry in bundle.catalog.credentials:
        if entry.ref.service not in provider_index:
            message = f"credential {entry.ref.name} names unknown provider {entry.ref.service}"
            raise ValueError(message)
        if entry.ref.workspace_id is not None and entry.ref.org_id is None:
            message = f"workspace credential {entry.ref.name} must belong to an organization"
            raise ValueError(message)
        if entry.ref.org_id is not None and entry.ref.org_id != bundle.org_id:
            message = f"credential {entry.ref.name} belongs to another organization"
            raise ValueError(message)
        if entry.ref.secret_id in secret_ids:
            message = f"duplicate credential secret id {entry.ref.secret_id}"
            raise ValueError(message)
        secret_ids.add(entry.ref.secret_id)
