from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from conftest import ORG, WORKSPACE, make_bundle, make_key

from contract import KeyEntry, uuid7
from contract.budgets import (
    BudgetState,
    KeyBudgetBucket,
    OrgPolicyState,
    PolicyState,
    PolicyStateRequest,
    SharedBudgetBucket,
    budget_window,
)
from contract.policies import AllRequests, Budget, PolicyDefinition, PolicyEntry, RequestMatch, RuleDefinition, SelectedUsers, WorkspaceTarget
from data_plane.budgets import BudgetStateHolder, BudgetStatePoller, ControlPlaneBudgetBackend, NoBudgetBackend, build_budget_backend
from data_plane.bundle.holder import BundleHolder, BundleSet, BundleSnapshot
from data_plane.canonical import CanonicalRequest
from data_plane.config import ControlPlaneBudgetConfig, NoBudgetConfig
from data_plane.control_plane_link import ControlPlaneLink
from data_plane.errors import RequestRejectedError
from data_plane.metrics import DataPlaneMetrics
from data_plane.policies import CompiledRule, matching_rules


def _budget_rules(request: CanonicalRequest, key: KeyEntry, snapshot: BundleSnapshot) -> tuple[CompiledRule, ...]:
    return tuple(rule for rule in matching_rules(request, key, snapshot.policy_index) if isinstance(rule.definition.action, Budget))


def test_budget_state_is_independent_of_bundle_identity_and_expires():
    now = datetime.now(UTC)
    start, end = budget_window("month", now)
    _, key = make_key()
    request = CanonicalRequest(model="gpt-test", messages=[{"role": "user", "content": "hello"}])
    holder = BudgetStateHolder()
    state = BudgetState(
        policy_id=uuid7(),
        rule_index=0,
        workspace_id=WORKSPACE,
        target=WorkspaceTarget(kind="workspace"),
        match=AllRequests(kind="all_requests"),
        amount_usd="100",
        period="month",
        window_start=start,
        window_end=end,
        aggregation="shared",
        exhausted_buckets=(SharedBudgetBucket(),),
    )
    policy = PolicyEntry(
        id=state.policy_id,
        workspace_id=WORKSPACE,
        name="Budget",
        priority=100,
        definition=PolicyDefinition(
            target=state.target,
            rules=(
                RuleDefinition(
                    match=state.match,
                    action=Budget(kind="budget", amount_usd=state.amount_usd, period=state.period, aggregation=state.aggregation),
                ),
            ),
        ),
    )
    holder.adopt(PolicyState(computed_at=now, organizations=(OrgPolicyState(org_id=ORG, budgets=(state,)),)))
    for _ in range(2):
        snapshot = BundleSnapshot.from_bundle(make_bundle(keys=[key]).model_copy(update={"policies": (policy,)}))
        with pytest.raises(RequestRejectedError) as denied:
            holder.check(_budget_rules(request, key, snapshot), key, now)
        assert denied.value.code == "budget_exhausted"
        assert denied.value.status == 429
        assert holder.check(_budget_rules(request, key, snapshot), key, end + timedelta(seconds=1)) == "expired"
    revised_rule = RuleDefinition(
        match=state.match,
        action=Budget(kind="budget", amount_usd="101", period=state.period, aggregation=state.aggregation),
    )
    revised_policy = policy.model_copy(update={"definition": policy.definition.model_copy(update={"rules": (revised_rule,)})})
    revised_snapshot = BundleSnapshot.from_bundle(make_bundle(keys=[key]).model_copy(update={"policies": (revised_policy,)}))
    assert holder.check(_budget_rules(request, key, revised_snapshot), key, now) == "mismatch"
    holder.adopt(PolicyState(computed_at=now, organizations=(OrgPolicyState(org_id=ORG, budgets=()),)))
    snapshot = BundleSnapshot.from_bundle(make_bundle(keys=[key]))
    holder.check(_budget_rules(request, key, snapshot), key, now)


def test_per_key_filters_use_original_request_and_all_matching_budgets():

    now = datetime.now(UTC)
    start, end = budget_window("day", now)
    _, key = make_key("first")
    _, other_key = make_key("second")
    request = CanonicalRequest(
        model="original", messages=[{"role": "user", "content": "hello"}], stream=True, response_format={"type": "json_object"}
    )
    snapshot = BundleSnapshot.from_bundle(make_bundle(keys=[key, other_key]))
    budget = BudgetState(
        policy_id=uuid7(),
        rule_index=0,
        workspace_id=WORKSPACE,
        target=SelectedUsers(kind="selected_users", user_ids=(key.user_id,)),
        match=RequestMatch(kind="request", models=("original",), stream=True, capabilities=("structured_output",)),
        amount_usd="10",
        period="day",
        window_start=start,
        window_end=end,
        aggregation="per_key",
        exhausted_buckets=(KeyBudgetBucket(key_id=key.key_id),),
    )
    policy = PolicyEntry(
        id=budget.policy_id,
        workspace_id=WORKSPACE,
        name="Budget",
        priority=100,
        definition=PolicyDefinition(
            target=budget.target,
            rules=(
                RuleDefinition(
                    match=budget.match,
                    action=Budget(kind="budget", amount_usd=budget.amount_usd, period=budget.period, aggregation=budget.aggregation),
                ),
            ),
        ),
    )
    snapshot = BundleSnapshot.from_bundle(make_bundle(keys=[key, other_key]).model_copy(update={"policies": (policy,)}))
    holder = BudgetStateHolder()
    holder.adopt(PolicyState(computed_at=now, organizations=(OrgPolicyState(org_id=ORG, budgets=(budget,)),)))
    with pytest.raises(RequestRejectedError, match="budget_exhausted"):
        holder.check(_budget_rules(request, key, snapshot), key, now)
    holder.check(_budget_rules(request, other_key, snapshot), other_key, now)
    for unmatched in (
        request.model_copy(update={"model": "fallback"}),
        request.model_copy(update={"stream": False}),
        request.model_copy(update={"response_format": None}),
    ):
        holder.check(_budget_rules(unmatched, key, snapshot), key, now)


def test_uninitialized_budget_state_allows_matching_requests():

    _, key = make_key()
    policy = PolicyEntry(
        id=uuid7(),
        workspace_id=WORKSPACE,
        name="Budget",
        priority=100,
        definition=PolicyDefinition(
            target=WorkspaceTarget(kind="workspace"),
            rules=(
                RuleDefinition.model_validate(
                    {
                        "match": {"kind": "request", "stream": True},
                        "action": {"kind": "budget", "period": "month", "amount_usd": "10", "aggregation": "shared"},
                    }
                ),
            ),
        ),
    )
    snapshot = BundleSnapshot.from_bundle(make_bundle(keys=[key]).model_copy(update={"policies": (policy,)}))
    holder = BudgetStateHolder()
    request = CanonicalRequest(model="gpt-test", messages=[{"role": "user", "content": "hello"}], stream=True)
    assert holder.check(_budget_rules(request, key, snapshot), key, datetime.now(UTC)) == "missing"
    unmatched = request.model_copy(update={"stream": False})
    assert holder.check(_budget_rules(unmatched, key, snapshot), key, datetime.now(UTC)) is None


def test_no_budget_config_builds_no_budget_backend():
    metrics = DataPlaneMetrics()
    bundles = BundleHolder(metrics)
    client = httpx2.AsyncClient()
    try:
        backend = build_budget_backend(NoBudgetConfig(), bundles, client, metrics)
        assert isinstance(backend, NoBudgetBackend)
    finally:
        asyncio.run(client.aclose())
        metrics.shutdown()


def test_control_plane_budget_backend_uses_its_own_configuration():
    metrics = DataPlaneMetrics()
    bundles = BundleHolder(metrics)
    client = httpx2.AsyncClient()
    config = ControlPlaneBudgetConfig(control_plane=ControlPlaneLink(url="http://budget-cp.test", management_key="budget-token"), poll_interval_s=11)
    try:
        backend = build_budget_backend(config, bundles, client, metrics)
        assert isinstance(backend, ControlPlaneBudgetBackend)
    finally:
        asyncio.run(client.aclose())
        metrics.shutdown()


async def test_failed_or_incomplete_refresh_keeps_the_last_complete_snapshot():

    now = datetime.now(UTC)
    start, end = budget_window("day", now)
    _, key = make_key()
    state = BudgetState(
        policy_id=uuid7(),
        rule_index=0,
        workspace_id=WORKSPACE,
        target=WorkspaceTarget(kind="workspace"),
        match=AllRequests(kind="all_requests"),
        amount_usd="1",
        period="day",
        window_start=start,
        window_end=end,
        aggregation="shared",
        exhausted_buckets=(SharedBudgetBucket(),),
    )
    payload = PolicyState(computed_at=now, organizations=(OrgPolicyState(org_id=ORG, budgets=(state,)),))
    response = httpx2.Response(200, json={"data": payload.model_dump(mode="json")})

    def respond(request):
        assert PolicyStateRequest.model_validate_json(request.content).org_ids == (ORG,)
        return response

    metrics = DataPlaneMetrics()
    bundles = BundleHolder(metrics)
    policy = PolicyEntry(
        id=state.policy_id,
        workspace_id=WORKSPACE,
        name="Budget",
        priority=100,
        definition=PolicyDefinition(
            target=state.target,
            rules=(
                RuleDefinition(
                    match=state.match,
                    action=Budget(kind="budget", amount_usd=state.amount_usd, period=state.period, aggregation=state.aggregation),
                ),
            ),
        ),
    )
    bundles.swap(BundleSet.from_bundles((make_bundle(keys=[key]).model_copy(update={"policies": (policy,)}),)), "test")
    holder = BudgetStateHolder()
    try:
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
            poller = BudgetStatePoller(ControlPlaneLink(url="http://cp.test", management_key="test"), bundles, holder, client, metrics)
            await poller.once()
            for failed_response in (httpx2.Response(503), httpx2.Response(200, json={"data": {"computed_at": now.isoformat(), "organizations": []}})):
                response = failed_response
                with pytest.raises((httpx2.HTTPStatusError, ValueError)):
                    await poller.once()
                request = CanonicalRequest(model="gpt-test", messages=[{"role": "user", "content": "hello"}])
                snapshot = bundles.current.snapshots[ORG]
                with pytest.raises(RequestRejectedError, match="budget_exhausted"):
                    holder.check(_budget_rules(request, key, snapshot), key, now)
            assert holder.computed_at == now
    finally:
        metrics.shutdown()
