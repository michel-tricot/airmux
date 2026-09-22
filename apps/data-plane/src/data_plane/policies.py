from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby
from types import MappingProxyType
from typing import TYPE_CHECKING

from contract.policies import MAX_WORKSPACE_RULES, Fallback, PolicyEntry, RequestMatch, RuleDefinition, SelectedKeys, SelectedUsers
from data_plane.policy_actions import require_evaluator

if TYPE_CHECKING:
    from collections.abc import Mapping
    from uuid import UUID

    from contract import Capability, KeyEntry
    from data_plane.canonical import CanonicalRequest
    from data_plane.requirements import RequestRequirements


@dataclass(frozen=True)
class CompiledRule:
    policy: PolicyEntry
    rule_index: int
    definition: RuleDefinition
    selected_key_ids: frozenset[str] | None
    selected_user_ids: frozenset[UUID] | None
    models: frozenset[str]
    capabilities: frozenset[Capability]


type PolicyIndex = Mapping[UUID, tuple[CompiledRule, ...]]


def compile_policies(policies: tuple[PolicyEntry, ...]) -> PolicyIndex:
    if len({policy.id for policy in policies}) != len(policies):
        msg = "Duplicate policy id"
        raise ValueError(msg)
    ordered = sorted(policies, key=lambda policy: (policy.workspace_id, policy.priority, policy.id))
    grouped = tuple((workspace_id, tuple(entries)) for workspace_id, entries in groupby(ordered, key=lambda policy: policy.workspace_id))
    if any(sum(len(policy.definition.rules) for policy in entries) > MAX_WORKSPACE_RULES for _, entries in grouped):
        msg = f"A workspace may contain at most {MAX_WORKSPACE_RULES} active policy rules"
        raise ValueError(msg)
    for policy in policies:
        if len(set(policy.definition.rules)) != len(policy.definition.rules):
            msg = f"Policy {policy.id} contains duplicate rules"
            raise ValueError(msg)
        if sum(isinstance(rule.action, Fallback) for rule in policy.definition.rules) > 1:
            msg = f"Policy {policy.id} may contain at most one fallback rule"
            raise ValueError(msg)
        for rule in policy.definition.rules:
            require_evaluator(rule.action)
    return MappingProxyType(
        {
            workspace_id: tuple(
                CompiledRule(
                    policy=policy,
                    rule_index=rule_index,
                    definition=rule,
                    selected_key_ids=(frozenset(policy.definition.target.key_ids) if isinstance(policy.definition.target, SelectedKeys) else None),
                    selected_user_ids=(frozenset(policy.definition.target.user_ids) if isinstance(policy.definition.target, SelectedUsers) else None),
                    models=frozenset(rule.match.models) if isinstance(rule.match, RequestMatch) else frozenset(),
                    capabilities=frozenset(rule.match.capabilities) if isinstance(rule.match, RequestMatch) else frozenset(),
                )
                for policy in entries
                for rule_index, rule in enumerate(policy.definition.rules)
            )
            for workspace_id, entries in grouped
        }
    )


def matching_rules(request: CanonicalRequest, key: KeyEntry, index: PolicyIndex, requirements: RequestRequirements) -> tuple[CompiledRule, ...]:
    candidates = index.get(key.workspace_id, ())
    if not candidates:
        return ()
    return tuple(entry for entry in candidates if _matches(entry, request, key, requirements.capabilities))


def matching_model_rules(model_id: str, key: KeyEntry, index: PolicyIndex) -> tuple[CompiledRule, ...]:
    return tuple(
        entry
        for entry in index.get(key.workspace_id, ())
        if _matches_model(entry, model_id, key)
        and (not isinstance(match := entry.definition.match, RequestMatch) or (match.stream is None and not entry.capabilities))
    )


def _matches(entry: CompiledRule, request: CanonicalRequest, key: KeyEntry, capabilities: frozenset[Capability]) -> bool:
    if not _matches_model(entry, request.model, key):
        return False
    match = entry.definition.match
    if not isinstance(match, RequestMatch):
        return True
    stream_matches = match.stream is None or request.stream is match.stream
    return stream_matches and entry.capabilities <= capabilities


def _matches_model(entry: CompiledRule, model_id: str, key: KeyEntry) -> bool:
    return (
        (entry.selected_key_ids is None or key.key_id in entry.selected_key_ids)
        and (entry.selected_user_ids is None or key.user_id in entry.selected_user_ids)
        and (not entry.models or model_id in entry.models)
    )
