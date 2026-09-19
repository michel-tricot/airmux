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
    from data_plane.bundle.holder import BundleHolder, BundleSnapshot
    from data_plane.canonical import CanonicalRequest
    from data_plane.control_plane_link import ControlPlaneLink
    from data_plane.metrics import DataPlaneMetrics


@dataclass(frozen=True)
class _CompiledBudget:
    state: BudgetState
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
        self.computed_at: datetime | None = None

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
        self._organizations = MappingProxyType(organizations)
        self.computed_at = state.computed_at

    def check(self, request: CanonicalRequest, key: KeyEntry, snapshot: BundleSnapshot, now: datetime) -> None:
        workspaces = self._organizations.get(key.org_id)
        if workspaces is None:
            if any(isinstance(rule.definition.action, Budget) for rule in matching_rules(request, key, snapshot.budget_index)):
                raise RequestRejectedError(503, GatewayErrorCode.policy_state_unavailable, "Budget state has not loaded")
            return
        budgets = workspaces.get(key.workspace_id, ())
        if not budgets:
            return
        capabilities = requested_capabilities(request)
        for budget in budgets:
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
    supports_budgets = False

    def start(self, _task_group: asyncio.TaskGroup) -> tuple[asyncio.Task[None], ...]:
        return ()


class ControlPlaneBudgetBackend:
    supports_budgets = True

    def __init__(
        self,
        config: ControlPlaneBudgetConfig,
        bundles: BundleHolder,
        budgets: BudgetStateHolder,
        client: httpx.AsyncClient,
        metrics: DataPlaneMetrics,
    ) -> None:
        self._config = config
        self._bundles = bundles
        self._budgets = budgets
        self._client = client
        self._metrics = metrics

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
    budgets: BudgetStateHolder,
    client: httpx.AsyncClient,
    metrics: DataPlaneMetrics,
) -> BudgetBackend:
    if isinstance(config, ControlPlaneBudgetConfig):
        return ControlPlaneBudgetBackend(config, bundles, budgets, client, metrics)
    return NoBudgetBackend()
