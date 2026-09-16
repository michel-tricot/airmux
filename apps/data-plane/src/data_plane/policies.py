from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby
from types import MappingProxyType
from typing import TYPE_CHECKING

from contract.policies import MAX_WORKSPACE_RULES, Fallback, PolicyEntry, RequestMatch, RuleEntry, SelectedKeys, SelectedUsers
from data_plane.policy_actions import require_evaluator
from data_plane.requirements import required_capabilities

if TYPE_CHECKING:
    from collections.abc import Mapping
    from uuid import UUID

    from contract import Capability, KeyEntry
    from data_plane.canonical import CanonicalRequest


@dataclass(frozen=True)
class CompiledRule:
    policy: PolicyEntry
    rule: RuleEntry
    selected_key_ids: frozenset[str] | None
    selected_user_ids: frozenset[UUID] | None
    models: frozenset[str]
    capabilities: frozenset[Capability]


type PolicyIndex = Mapping[UUID, tuple[CompiledRule, ...]]


def compile_policies(policies: tuple[PolicyEntry, ...], rules: tuple[RuleEntry, ...]) -> PolicyIndex:
    if len({policy.id for policy in policies}) != len(policies):
        msg = "Duplicate policy id"
        raise ValueError(msg)
    rules_by_id = {rule.id: rule for rule in rules}
    if len(rules_by_id) != len(rules):
        msg = "Duplicate rule id"
        raise ValueError(msg)
    ordered = sorted(policies, key=lambda policy: (policy.workspace_id, policy.priority, policy.id))
    grouped = tuple((workspace_id, tuple(entries)) for workspace_id, entries in groupby(ordered, key=lambda policy: policy.workspace_id))
    if any(sum(len(policy.definition.rule_ids) for policy in entries) > MAX_WORKSPACE_RULES for _, entries in grouped):
        msg = f"A workspace may contain at most {MAX_WORKSPACE_RULES} active policy rules"
        raise ValueError(msg)
    for policy in policies:
        fallback_rules = 0
        for rule_id in policy.definition.rule_ids:
            rule = rules_by_id.get(rule_id)
            if rule is None:
                msg = f"Policy {policy.id} names unknown rule {rule_id}"
                raise ValueError(msg)
            if rule.workspace_id != policy.workspace_id:
                msg = f"Policy {policy.id} names rule {rule.id} from another workspace"
                raise ValueError(msg)
            if isinstance(rule.definition.action, Fallback):
                fallback_rules += 1
            require_evaluator(rule.definition.action)
        if fallback_rules > 1:
            msg = f"Policy {policy.id} may contain at most one fallback rule"
            raise ValueError(msg)
    return MappingProxyType(
        {
            workspace_id: tuple(
                CompiledRule(
                    policy=policy,
                    rule=rule,
                    selected_key_ids=(frozenset(policy.definition.target.key_ids) if isinstance(policy.definition.target, SelectedKeys) else None),
                    selected_user_ids=(frozenset(policy.definition.target.user_ids) if isinstance(policy.definition.target, SelectedUsers) else None),
                    models=frozenset(rule.definition.match.models) if isinstance(rule.definition.match, RequestMatch) else frozenset(),
                    capabilities=frozenset(rule.definition.match.capabilities) if isinstance(rule.definition.match, RequestMatch) else frozenset(),
                )
                for policy in entries
                for rule_id in policy.definition.rule_ids
                for rule in (rules_by_id[rule_id],)
            )
            for workspace_id, entries in grouped
        }
    )


def matching_rules(request: CanonicalRequest, key: KeyEntry, index: PolicyIndex) -> tuple[CompiledRule, ...]:
    candidates = index.get(key.workspace_id, ())
    if not candidates:
        return ()
    capabilities = required_capabilities(request)
    return tuple(entry for entry in candidates if _matches(entry, request, key, capabilities))


def matching_model_rules(model_id: str, key: KeyEntry, index: PolicyIndex) -> tuple[CompiledRule, ...]:
    return tuple(
        entry
        for entry in index.get(key.workspace_id, ())
        if _matches_model(entry, model_id, key)
        and (not isinstance(match := entry.rule.definition.match, RequestMatch) or (match.stream is None and not entry.capabilities))
    )


def _matches(entry: CompiledRule, request: CanonicalRequest, key: KeyEntry, capabilities: frozenset[Capability]) -> bool:
    if not _matches_model(entry, request.model, key):
        return False
    match = entry.rule.definition.match
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
