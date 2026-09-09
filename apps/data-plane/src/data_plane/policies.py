from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby
from types import MappingProxyType
from typing import TYPE_CHECKING

from contract.policies import MAX_WORKSPACE_POLICIES, PolicyEntry, RequestMatch, SelectedKeys
from data_plane.policy_actions import require_evaluator
from data_plane.requirements import required_capabilities

if TYPE_CHECKING:
    from collections.abc import Mapping
    from uuid import UUID

    from contract import Capability, KeyEntry
    from data_plane.canonical import CanonicalRequest


@dataclass(frozen=True)
class CompiledPolicy:
    policy: PolicyEntry
    selected_key_ids: frozenset[str] | None
    models: frozenset[str]
    capabilities: frozenset[Capability]


type PolicyIndex = Mapping[UUID, tuple[CompiledPolicy, ...]]


def compile_policies(policies: tuple[PolicyEntry, ...]) -> PolicyIndex:
    if len({policy.id for policy in policies}) != len(policies):
        msg = "Duplicate policy id"
        raise ValueError(msg)
    ordered = sorted(policies, key=lambda policy: (policy.workspace_id, policy.priority, policy.id))
    grouped = tuple((workspace_id, tuple(entries)) for workspace_id, entries in groupby(ordered, key=lambda policy: policy.workspace_id))
    if any(len(entries) > MAX_WORKSPACE_POLICIES for _, entries in grouped):
        msg = "A workspace may contain at most 100 active policies"
        raise ValueError(msg)
    for policy in policies:
        require_evaluator(policy.definition.action)
    return MappingProxyType(
        {
            workspace_id: tuple(
                CompiledPolicy(
                    policy=policy,
                    selected_key_ids=(frozenset(policy.definition.target.key_ids) if isinstance(policy.definition.target, SelectedKeys) else None),
                    models=frozenset(policy.definition.match.models) if isinstance(policy.definition.match, RequestMatch) else frozenset(),
                    capabilities=(
                        frozenset(policy.definition.match.capabilities) if isinstance(policy.definition.match, RequestMatch) else frozenset()
                    ),
                )
                for policy in entries
            )
            for workspace_id, entries in grouped
        }
    )


def matching_policies(request: CanonicalRequest, key: KeyEntry, index: PolicyIndex) -> tuple[PolicyEntry, ...]:
    candidates = index.get(key.workspace_id, ())
    if not candidates:
        return ()
    capabilities = required_capabilities(request)
    return tuple(entry.policy for entry in candidates if _matches(entry, request, key, capabilities))


def _matches(entry: CompiledPolicy, request: CanonicalRequest, key: KeyEntry, capabilities: frozenset[Capability]) -> bool:
    if entry.selected_key_ids is not None and key.key_id not in entry.selected_key_ids:
        return False
    match = entry.policy.definition.match
    if not isinstance(match, RequestMatch):
        return True
    model_matches = not entry.models or request.model in entry.models
    stream_matches = match.stream is None or request.stream is match.stream
    return model_matches and stream_matches and entry.capabilities <= capabilities
