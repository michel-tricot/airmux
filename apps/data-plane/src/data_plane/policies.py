from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby
from types import MappingProxyType
from typing import TYPE_CHECKING

from cel_expr_python import cel

from contract.policies import MAX_WORKSPACE_POLICIES, BudgetPlaceholder, PolicyEntry, SelectedKeys, compile_condition, condition_environment

if TYPE_CHECKING:
    from collections.abc import Mapping
    from uuid import UUID

    from contract import KeyEntry
    from data_plane.canonical import CanonicalRequest


@dataclass(frozen=True)
class CompiledPolicy:
    policy: PolicyEntry
    condition: cel.Expression
    selected_key_ids: frozenset[str] | None


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
    return MappingProxyType(
        {
            workspace_id: tuple(
                CompiledPolicy(
                    policy,
                    compile_condition(policy.definition.condition),
                    frozenset(policy.definition.target.key_ids) if isinstance(policy.definition.target, SelectedKeys) else None,
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
    facts = {"request_model": request.model, "request_stream": request.stream, "key_id": key.key_id, "workspace_id": str(key.workspace_id)}
    context = condition_environment().Activation(facts)
    return tuple(entry.policy for entry in candidates if _matches(entry, key, context))


def _matches(entry: CompiledPolicy, key: KeyEntry, context: cel.Activation) -> bool:
    if isinstance(entry.policy.definition.action, BudgetPlaceholder):
        return False
    if entry.selected_key_ids is not None and key.key_id not in entry.selected_key_ids:
        return False
    result = entry.condition.eval(context)
    if result.type() != cel.Type.BOOL:
        msg = f"Policy {entry.policy.name} could not be evaluated"
        raise ValueError(msg)
    return result.plain_value() is True
