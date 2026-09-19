from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from conftest import ORG, WORKSPACE, make_bundle, make_key

from contract import uuid7
from contract.budgets import OrgPolicyState, PerKeyBudgetState, PolicyState, PolicyStateRequest, SharedBudgetState, budget_window
from contract.policies import AllRequests, PolicyDefinition, PolicyEntry, RequestMatch, RuleDefinition, SelectedUsers, WorkspaceTarget
from data_plane.budgets import BudgetStateHolder, BudgetStatePoller
from data_plane.bundle.holder import BundleHolder, BundleSet, BundleSnapshot
from data_plane.canonical import CanonicalRequest
from data_plane.control_plane_link import ControlPlaneLink
from data_plane.errors import RequestRejectedError
from data_plane.metrics import DataPlaneMetrics


def test_budget_state_is_independent_of_bundle_identity_and_expires():
    now = datetime.now(UTC)
    start, end = budget_window("month", now)
    _, key = make_key()
    request = CanonicalRequest(model="gpt-test", messages=[{"role": "user", "content": "hello"}])
    holder = BudgetStateHolder()
    state = SharedBudgetState(
        policy_id=uuid7(),
        rule_index=1,
        workspace_id=WORKSPACE,
        target=WorkspaceTarget(kind="workspace"),
        match=AllRequests(kind="all_requests"),
        amount_usd="100",
        period="month",
        window_start=start,
        window_end=end,
        exhausted=True,
    )
    holder.adopt(PolicyState(computed_at=now, organizations=(OrgPolicyState(org_id=ORG, budgets=(state,)),)))
    for _ in range(2):
        snapshot = BundleSnapshot.from_bundle(make_bundle(keys=[key]))
        with pytest.raises(RequestRejectedError) as denied:
            holder.check(request, key, snapshot, now)
        assert denied.value.code == "budget_exhausted"
        assert denied.value.status == 429
        holder.check(request, key, snapshot, end + timedelta(seconds=1))
    holder.adopt(PolicyState(computed_at=now, organizations=(OrgPolicyState(org_id=ORG, budgets=()),)))
    holder.check(request, key, snapshot, now)


def test_per_key_filters_use_original_request_and_all_matching_budgets():

    now = datetime.now(UTC)
    start, end = budget_window("day", now)
    _, key = make_key("first")
    _, other_key = make_key("second")
    request = CanonicalRequest(
        model="original", messages=[{"role": "user", "content": "hello"}], stream=True, response_format={"type": "json_object"}
    )
    snapshot = BundleSnapshot.from_bundle(make_bundle(keys=[key, other_key]))
    budget = PerKeyBudgetState(
        policy_id=uuid7(),
        rule_index=0,
        workspace_id=WORKSPACE,
        target=SelectedUsers(kind="selected_users", user_ids=(key.user_id,)),
        match=RequestMatch(kind="request", models=("original",), stream=True, capabilities=("structured_output",)),
        amount_usd="10",
        period="day",
        window_start=start,
        window_end=end,
        exhausted_key_ids=frozenset({key.key_id}),
    )
    holder = BudgetStateHolder()
    holder.adopt(PolicyState(computed_at=now, organizations=(OrgPolicyState(org_id=ORG, budgets=(budget,)),)))
    with pytest.raises(RequestRejectedError, match="budget_exhausted"):
        holder.check(request, key, snapshot, now)
    holder.check(request, other_key, snapshot, now)
    holder.check(request.model_copy(update={"model": "fallback"}), key, snapshot, now)
    holder.check(request.model_copy(update={"stream": False}), key, snapshot, now)
    holder.check(request.model_copy(update={"response_format": None}), key, snapshot, now)


def test_uninitialized_budget_state_only_blocks_matching_requests():

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
                        "action": {"kind": "budget", "period": "month", "amount_usd": "10", "sharing": "shared"},
                    }
                ),
            ),
        ),
    )
    snapshot = BundleSnapshot.from_bundle(make_bundle(keys=[key]).model_copy(update={"policies": (policy,)}))
    holder = BudgetStateHolder()
    request = CanonicalRequest(model="gpt-test", messages=[{"role": "user", "content": "hello"}], stream=True)
    with pytest.raises(RequestRejectedError, match="policy_state_unavailable"):
        holder.check(request, key, snapshot, datetime.now(UTC))
    holder.check(request.model_copy(update={"stream": False}), key, snapshot, datetime.now(UTC))


def test_standalone_gateway_rejects_budget_bundle_without_replacing_previous_state():
    metrics = DataPlaneMetrics()
    holder = BundleHolder(metrics, supports_budgets=False)
    bundle = make_bundle()
    original = BundleSet.from_bundles((bundle,))
    holder.swap(original, "test")
    policy = PolicyEntry(
        id=uuid7(),
        workspace_id=WORKSPACE,
        name="Budget",
        priority=100,
        definition=PolicyDefinition.model_validate(
            {
                "target": {"kind": "workspace"},
                "rules": [
                    {
                        "match": {"kind": "all_requests"},
                        "action": {"kind": "budget", "period": "month", "amount_usd": "10", "sharing": "shared"},
                    }
                ],
            }
        ),
    )
    try:
        with pytest.raises(ValueError, match="remote bundles and event export"):
            holder.swap(BundleSet.from_bundles((bundle.model_copy(update={"policies": (policy,)}),)), "test")
        assert holder.current is original
    finally:
        metrics.shutdown()


async def test_failed_or_incomplete_refresh_keeps_the_last_complete_snapshot():

    now = datetime.now(UTC)
    start, end = budget_window("day", now)
    _, key = make_key()
    state = SharedBudgetState(
        policy_id=uuid7(),
        rule_index=0,
        workspace_id=WORKSPACE,
        target=WorkspaceTarget(kind="workspace"),
        match=AllRequests(kind="all_requests"),
        amount_usd="1",
        period="day",
        window_start=start,
        window_end=end,
        exhausted=True,
    )
    payload = PolicyState(computed_at=now, organizations=(OrgPolicyState(org_id=ORG, budgets=(state,)),))
    response = httpx.Response(200, json={"data": payload.model_dump(mode="json")})

    def respond(request):
        assert PolicyStateRequest.model_validate_json(request.content).org_ids == (ORG,)
        return response

    metrics = DataPlaneMetrics()
    bundles = BundleHolder(metrics)
    bundles.swap(BundleSet.from_bundles((make_bundle(keys=[key]),)), "test")
    holder = BudgetStateHolder()
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            poller = BudgetStatePoller(ControlPlaneLink(url="http://cp.test", management_key="test"), bundles, holder, client, metrics)
            await poller.once()
            for failed_response in (httpx.Response(503), httpx.Response(200, json={"data": {"computed_at": now.isoformat(), "organizations": []}})):
                response = failed_response
                with pytest.raises((httpx.HTTPStatusError, ValueError)):
                    await poller.once()
                with pytest.raises(RequestRejectedError, match="budget_exhausted"):
                    holder.check(
                        CanonicalRequest(model="gpt-test", messages=[{"role": "user", "content": "hello"}]), key, bundles.current.snapshots[ORG], now
                    )
            assert holder.computed_at == now
    finally:
        metrics.shutdown()
