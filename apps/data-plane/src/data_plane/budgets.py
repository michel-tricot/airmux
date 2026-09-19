from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import groupby
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

import httpx
from pydantic import ValidationError

from contract.budgets import BudgetBucket, BudgetState, KeyBudgetBucket, PolicyState, PolicyStateRequest
from contract.policies import Budget, BudgetAggregation, RequestMatch, SelectedKeys, SelectedUsers
from data_plane.canonical import GatewayErrorCode
from data_plane.config import BudgetConfig, ControlPlaneBudgetConfig
from data_plane.errors import RequestRejectedError
from data_plane.policies import matching_rules
from data_plane.requirements import requested_capabilities
from data_plane.tasks import run_periodic

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Callable, Mapping
    from datetime import datetime
    from uuid import UUID

    from contract import KeyEntry
    from contract.model_types import RequestCapability
    from data_plane.bundle.holder import BundleSnapshot
    from data_plane.canonical import CanonicalRequest
    from data_plane.control_plane_link import ControlPlaneLink
    from data_plane.metrics import DataPlaneMetrics
    from data_plane.policies import CompiledRule


@dataclass(frozen=True)
class _CompiledBudget:
    state: BudgetState
    rule_key: tuple[UUID, int]
    key_ids: frozenset[str] | None
    user_ids: frozenset[UUID] | None
    models: frozenset[str]
    capabilities: frozenset[RequestCapability]
    bucket_for: Callable[[KeyEntry], str | UUID | None]
    exhausted_buckets: frozenset[str | UUID | None]

    def matches(self, request: CanonicalRequest, key: KeyEntry, capabilities: frozenset[RequestCapability]) -> bool:
        match = self.state.match
        return (
            (self.key_ids is None or key.key_id in self.key_ids)
            and (self.user_ids is None or key.user_id in self.user_ids)
            and (not self.models or request.model in self.models)
            and (not isinstance(match, RequestMatch) or match.stream is None or request.stream is match.stream)
            and self.capabilities <= capabilities
        )


def _compile(state: BudgetState) -> _CompiledBudget:
    return _CompiledBudget(
        state=state,
        rule_key=(state.policy_id, state.rule_index),
        key_ids=frozenset(state.target.key_ids) if isinstance(state.target, SelectedKeys) else None,
        user_ids=frozenset(state.target.user_ids) if isinstance(state.target, SelectedUsers) else None,
        models=frozenset(state.match.models) if isinstance(state.match, RequestMatch) else frozenset(),
        capabilities=frozenset(state.match.capabilities) if isinstance(state.match, RequestMatch) else frozenset(),
        bucket_for=_BUCKET_FOR_AGGREGATION[state.aggregation],
        exhausted_buckets=frozenset(_BUCKET_ID_FOR_AGGREGATION[state.aggregation](bucket) for bucket in state.exhausted_buckets),
    )


def _shared_bucket(_key: KeyEntry) -> None:
    return None


def _key_bucket(key: KeyEntry) -> str:
    return key.key_id


_BUCKET_FOR_AGGREGATION: dict[BudgetAggregation, Callable[[KeyEntry], str | UUID | None]] = {
    "shared": _shared_bucket,
    "per_key": _key_bucket,
}


def _shared_bucket_id(_bucket: BudgetBucket) -> None:
    return None


def _key_bucket_id(bucket: BudgetBucket) -> str:
    return cast("KeyBudgetBucket", bucket).key_id


_BUCKET_ID_FOR_AGGREGATION: dict[BudgetAggregation, Callable[[BudgetBucket], str | UUID | None]] = {
    "shared": _shared_bucket_id,
    "per_key": _key_bucket_id,
}


class BudgetStateHolder:
    def __init__(self) -> None:
        self._organizations: Mapping[UUID, Mapping[UUID, tuple[_CompiledBudget, ...]]] = MappingProxyType({})
        self._tracked_orgs: set[UUID] = set()
        self.computed_at: datetime | None = None

    def request_state(self, org_id: UUID) -> None:
        self._tracked_orgs.add(org_id)

    def requested_orgs(self) -> tuple[UUID, ...]:
        return tuple(self._tracked_orgs)

    def adopt(self, state: PolicyState) -> None:
        organizations = {
            org.org_id: MappingProxyType(
                {
                    workspace_id: tuple(_compile(budget) for budget in budgets)
                    for workspace_id, budgets in groupby(
                        sorted(org.budgets, key=lambda budget: budget.workspace_id), lambda budget: budget.workspace_id
                    )
                }
            )
            for org in state.organizations
        }
        current = dict(self._organizations)
        current.update(organizations)
        self._organizations = MappingProxyType(current)
        self.computed_at = state.computed_at

    def check(self, request: CanonicalRequest, key: KeyEntry, snapshot: BundleSnapshot, now: datetime) -> None:
        matching = tuple(rule for rule in matching_rules(request, key, snapshot.budget_index) if isinstance(rule.definition.action, Budget))
        if not matching:
            return
        workspaces = self._organizations.get(key.org_id)
        if workspaces is None:
            self.request_state(key.org_id)
            raise RequestRejectedError(503, GatewayErrorCode.policy_state_unavailable, "Budget state has not loaded")
        budgets = workspaces.get(key.workspace_id, ())
        budget_by_rule = {budget.rule_key: budget for budget in budgets}
        if any(
            (budget := budget_by_rule.get((rule.policy.id, rule.rule_index))) is None or not _state_matches_rule(budget, rule)
            for rule in matching
        ):
            self.request_state(key.org_id)
            raise RequestRejectedError(503, GatewayErrorCode.policy_state_unavailable, "Budget state has not loaded")
        capabilities = requested_capabilities(request)
        for rule in matching:
            budget = budget_by_rule[(rule.policy.id, rule.rule_index)]
            state = budget.state
            if not state.window_start <= now < state.window_end or not budget.matches(request, key, capabilities):
                continue
            if budget.bucket_for(key) in budget.exhausted_buckets:
                raise RequestRejectedError(
                    429,
                    GatewayErrorCode.budget_exhausted,
                    f"Estimated cost budget exhausted until {state.window_end.isoformat()}",
                    retry_after=max(1, math.ceil((state.window_end - now).total_seconds())),
                )


def _state_matches_rule(budget: _CompiledBudget, rule: CompiledRule) -> bool:
    action = cast("Budget", rule.definition.action)
    state = budget.state
    return (
        state.target == rule.policy.definition.target
        and state.match == rule.definition.match
        and state.aggregation == action.aggregation
        and state.amount_usd == action.amount_usd
        and state.period == action.period
    )


class BudgetStatePoller:
    def __init__(
        self,
        control_plane: ControlPlaneLink,
        budgets: BudgetStateHolder,
        client: httpx.AsyncClient,
        metrics: DataPlaneMetrics,
    ) -> None:
        self._metrics = metrics
        self._control_plane = control_plane
        self._budgets = budgets
        self._client = client

    async def once(self) -> None:
        org_ids = self._budgets.requested_orgs()
        if not org_ids:
            return
        response = await self._client.post(
            f"{self._control_plane.url}/api/v1/policy-state/sync",
            headers={"authorization": f"Bearer {self._control_plane.management_key}"},
            json=PolicyStateRequest(org_ids=org_ids).model_dump(mode="json"),
            timeout=5.0,
        )
        response.raise_for_status()
        state = PolicyState.model_validate(response.json()["data"])
        if {org.org_id for org in state.organizations} != set(org_ids):
            message = "Budget state must contain every requested organization exactly once"
            raise ValueError(message)
        self._budgets.adopt(state)
        self._metrics.observe_budget_state(state.computed_at.timestamp())

    async def run(self, poll_interval_s: float = 5.0) -> None:
        await run_periodic(self.once, poll_interval_s, (httpx.HTTPError, ValueError, ValidationError, KeyError), "budget state poll")


class NoBudgetBackend:
    def check(self, request: CanonicalRequest, key: KeyEntry, snapshot: BundleSnapshot, _now: datetime) -> None:
        if any(isinstance(rule.definition.action, Budget) for rule in matching_rules(request, key, snapshot.budget_index)):
            raise RequestRejectedError(503, GatewayErrorCode.policy_state_unavailable, "Budget backend is not configured")

    def start(self, _task_group: asyncio.TaskGroup) -> tuple[asyncio.Task[None], ...]:
        return ()


class ControlPlaneBudgetBackend:
    def __init__(
        self,
        config: ControlPlaneBudgetConfig,
        client: httpx.AsyncClient,
        metrics: DataPlaneMetrics,
    ) -> None:
        self._config = config
        self._budgets = BudgetStateHolder()
        self._client = client
        self._metrics = metrics

    def check(self, request: CanonicalRequest, key: KeyEntry, snapshot: BundleSnapshot, now: datetime) -> None:
        self._budgets.check(request, key, snapshot, now)

    def start(self, task_group: asyncio.TaskGroup) -> tuple[asyncio.Task[None], ...]:
        poller = BudgetStatePoller(
            self._config.control_plane,
            self._budgets,
            self._client,
            self._metrics,
        )
        return (task_group.create_task(poller.run(self._config.poll_interval_s), name="budget state poll"),)


BudgetBackend = NoBudgetBackend | ControlPlaneBudgetBackend


def build_budget_backend(
    config: BudgetConfig,
    client: httpx.AsyncClient,
    metrics: DataPlaneMetrics,
) -> BudgetBackend:
    if isinstance(config, ControlPlaneBudgetConfig):
        return ControlPlaneBudgetBackend(config, client, metrics)
    return NoBudgetBackend()
