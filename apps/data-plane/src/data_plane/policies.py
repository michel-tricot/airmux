from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from cel_expr_python import cel

from contract.policies import MAX_WORKSPACE_POLICIES, AllKeys, BudgetPlaceholder, PolicyEntry, compile_condition, condition_environment

if TYPE_CHECKING:
    from collections.abc import Mapping
    from uuid import UUID

    from contract import KeyEntry
    from data_plane.canonical import CanonicalRequest


@dataclass(frozen=True)
class CompiledPolicy:
    policy: PolicyEntry
    condition: cel.Expression


type PolicyIndex = Mapping[UUID, tuple[CompiledPolicy, ...]]


def compile_policies(policies: tuple[PolicyEntry, ...]) -> PolicyIndex:
    if len({policy.id for policy in policies}) != len(policies):
        msg = "Duplicate policy id"
        raise ValueError(msg)
    workspaces = frozenset(policy.workspace_id for policy in policies)
    if any(sum(policy.workspace_id == workspace for policy in policies) > MAX_WORKSPACE_POLICIES for workspace in workspaces):
        msg = "A workspace may contain at most 100 active policies"
        raise ValueError(msg)
    compiled = tuple(
        CompiledPolicy(policy, compile_condition(policy.definition.condition)) for policy in sorted(policies, key=lambda p: (p.priority, p.id))
    )
    return MappingProxyType({workspace: tuple(entry for entry in compiled if entry.policy.workspace_id == workspace) for workspace in workspaces})


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
    target = entry.policy.definition.target
    if not isinstance(target, AllKeys) and key.key_id not in target.key_ids:
        return False
    result = entry.condition.eval(context)
    if result.type() != cel.Type.BOOL:
        msg = f"Policy {entry.policy.name} could not be evaluated"
        raise ValueError(msg)
    return result.plain_value() is True
