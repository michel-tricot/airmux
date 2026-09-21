from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from itertools import batched, groupby
from types import MappingProxyType
from typing import TYPE_CHECKING, override

import httpx
from pydantic import ValidationError

from contract.budgets import BudgetState, KeyBudgetBucket, PolicyState, PolicyStateRequest
from contract.policies import Budget
from data_plane.canonical import GatewayErrorCode
from data_plane.config import BudgetConfig, ControlPlaneBudgetConfig
from data_plane.errors import RequestRejectedError
from data_plane.tasks import run_periodic

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Mapping
    from datetime import datetime
    from uuid import UUID

    from contract import KeyEntry
    from data_plane.bundle.holder import BundleHolder
    from data_plane.control_plane_link import ControlPlaneLink
    from data_plane.metrics import BudgetStateFallback, DataPlaneMetrics
    from data_plane.policies import CompiledRule


@dataclass(frozen=True)
class _CompiledBudget(ABC):
    state: BudgetState

    @property
    def rule_key(self) -> tuple[UUID, int]:
        return self.state.policy_id, self.state.rule_index

    @abstractmethod
    def exhausted_for(self, key: KeyEntry) -> bool: ...


@dataclass(frozen=True)
class _SharedBudget(_CompiledBudget):
    exhausted: bool

    @override
    def exhausted_for(self, key: KeyEntry) -> bool:
        return self.exhausted


@dataclass(frozen=True)
class _PerKeyBudget(_CompiledBudget):
    exhausted_key_ids: frozenset[str]

    @override
    def exhausted_for(self, key: KeyEntry) -> bool:
        return key.key_id in self.exhausted_key_ids


def _compile(state: BudgetState) -> _CompiledBudget:
    if state.aggregation == "shared":
        return _SharedBudget(state=state, exhausted=bool(state.exhausted_buckets))
    return _PerKeyBudget(
        state=state,
        exhausted_key_ids=frozenset(bucket.key_id for bucket in state.exhausted_buckets if isinstance(bucket, KeyBudgetBucket)),
    )


class BudgetStateHolder:
    def __init__(self) -> None:
        self._organizations: Mapping[UUID, Mapping[UUID, Mapping[tuple[UUID, int], _CompiledBudget]]] = MappingProxyType({})
        self.computed_at: datetime | None = None

    def adopt(self, state: PolicyState) -> None:
        organizations = {
            org.org_id: MappingProxyType(
                {
                    workspace_id: MappingProxyType({budget.rule_key: budget for budget in map(_compile, budgets)})
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

    def check(self, rules: tuple[CompiledRule, ...], key: KeyEntry, now: datetime) -> BudgetStateFallback | None:
        if not rules:
            return None
        workspaces = self._organizations.get(key.org_id)
        if workspaces is None:
            return "missing"
        budget_by_rule = workspaces.get(key.workspace_id, {})
        fallback: BudgetStateFallback | None = None
        for rule in rules:
            budget = budget_by_rule.get((rule.policy.id, rule.rule_index))
            if budget is None:
                fallback = fallback or "missing"
                continue
            if not _state_matches_rule(budget, rule):
                fallback = fallback or "mismatch"
                continue
            state = budget.state
            if not state.window_start <= now < state.window_end:
                fallback = fallback or "expired"
                continue
            if budget.exhausted_for(key):
                raise RequestRejectedError(
                    429,
                    GatewayErrorCode.budget_exhausted,
                    f"Estimated cost budget exhausted until {state.window_end.isoformat()}",
                    retry_after=max(1, math.ceil((state.window_end - now).total_seconds())),
                )
        return fallback


def _state_matches_rule(budget: _CompiledBudget, rule: CompiledRule) -> bool:
    action = rule.definition.action
    if not isinstance(action, Budget):
        return False
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
        bundles: BundleHolder,
        budgets: BudgetStateHolder,
        client: httpx.AsyncClient,
        metrics: DataPlaneMetrics,
    ) -> None:
        self._metrics = metrics
        self._control_plane = control_plane
        self._bundles = bundles
        self._budgets = budgets
        self._client = client

    async def once(self) -> None:
        org_ids = tuple(self._bundles.current.snapshots)
        states = tuple([await self._fetch(batch) for batch in batched(org_ids, 1000, strict=False)])
        if not states:
            return
        state = PolicyState(
            computed_at=min(item.computed_at for item in states),
            organizations=tuple(org for item in states for org in item.organizations),
        )
        self._budgets.adopt(state)
        self._metrics.observe_budget_state(state.computed_at.timestamp())

    async def _fetch(self, org_ids: tuple[UUID, ...]) -> PolicyState:
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
        return state

    async def run(self, poll_interval_s: float = 5.0) -> None:
        await run_periodic(self.once, poll_interval_s, (httpx.HTTPError, ValueError, ValidationError, KeyError), "budget state poll")


class NoBudgetBackend:
    def check(self, _rules: tuple[CompiledRule, ...], _key: KeyEntry, _now: datetime) -> None:
        pass

    def start(self, _task_group: asyncio.TaskGroup) -> tuple[asyncio.Task[None], ...]:
        return ()


class ControlPlaneBudgetBackend:
    def __init__(
        self,
        config: ControlPlaneBudgetConfig,
        bundles: BundleHolder,
        client: httpx.AsyncClient,
        metrics: DataPlaneMetrics,
    ) -> None:
        self._config = config
        self._bundles = bundles
        self._budgets = BudgetStateHolder()
        self._client = client
        self._metrics = metrics

    def check(self, rules: tuple[CompiledRule, ...], key: KeyEntry, now: datetime) -> None:
        fallback = self._budgets.check(rules, key, now)
        if fallback is not None:
            self._metrics.observe_budget_state_fallback(fallback)

    def start(self, task_group: asyncio.TaskGroup) -> tuple[asyncio.Task[None], ...]:
        poller = BudgetStatePoller(
            self._config.control_plane,
            self._bundles,
            self._budgets,
            self._client,
            self._metrics,
        )
        return (task_group.create_task(poller.run(self._config.poll_interval_s), name="budget state poll"),)


BudgetBackend = NoBudgetBackend | ControlPlaneBudgetBackend


def build_budget_backend(
    config: BudgetConfig,
    bundles: BundleHolder,
    client: httpx.AsyncClient,
    metrics: DataPlaneMetrics,
) -> BudgetBackend:
    if isinstance(config, ControlPlaneBudgetConfig):
        return ControlPlaneBudgetBackend(config, bundles, client, metrics)
    return NoBudgetBackend()
