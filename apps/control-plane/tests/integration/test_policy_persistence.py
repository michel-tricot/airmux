from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from helpers import make_org, make_workspace, setup_control_plane

from contract.policies import MAX_WORKSPACE_POLICIES, PolicyDefinition
from control_plane.db import standalone_transaction
from control_plane.models import Policy, set_actor
from control_plane.models.policy import InvalidPolicyError

DEFINITION = PolicyDefinition.model_validate({"target": {"kind": "all_keys"}, "match": {"kind": "all_requests"}, "action": {"kind": "byok"}})


@pytest.fixture
def policy_workspace(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "policies")
        workspace_id = make_workspace(client, cp.headers(org_id), "production")
    return cp, org_id, workspace_id


@pytest.mark.parametrize("operation", ["create", "enable"])
def test_policy_save_serializes_competing_writes_for_the_last_slot(policy_workspace, operation):
    cp, org_id, workspace_id = policy_workspace

    async def compete():
        async with standalone_transaction(cp.db_url):
            await set_actor("root")
            for position in range(MAX_WORKSPACE_POLICIES - 1):
                await Policy(org_id=org_id, workspace_id=workspace_id, name=f"existing-{position}", definition=DEFINITION).save()
            disabled = tuple(
                Policy(org_id=org_id, workspace_id=workspace_id, name=f"candidate-{position}", enabled=False, definition=DEFINITION)
                for position in range(2)
            )
            for policy in disabled:
                await policy.save()

        ready = asyncio.Barrier(2)

        async def save_candidate(position):
            try:
                async with standalone_transaction(cp.db_url):
                    await set_actor("root")
                    policies = await Policy.for_workspace(workspace_id)
                    await ready.wait()
                    policy = (
                        Policy(org_id=org_id, workspace_id=workspace_id, name=f"new-{position}", definition=DEFINITION)
                        if operation == "create"
                        else next(policy for policy in policies if policy.id == disabled[position].id)
                    )
                    policy.enabled = True
                    await policy.save()
            except InvalidPolicyError:
                return False
            else:
                return True

        async with asyncio.timeout(10):
            results = await asyncio.gather(save_candidate(0), save_candidate(1))
        async with standalone_transaction(cp.db_url):
            policies = await Policy.for_workspace(workspace_id)
        assert sorted(results) == [False, True]
        assert sum(policy.enabled for policy in policies) == MAX_WORKSPACE_POLICIES

    asyncio.run(compete())


@pytest.mark.parametrize(
    "definition",
    [
        PolicyDefinition.model_validate(
            {"target": {"kind": "all_keys"}, "match": {"kind": "request", "models": ["absent"]}, "action": {"kind": "byok"}}
        ),
        PolicyDefinition.model_validate(
            {"target": {"kind": "all_keys"}, "match": {"kind": "all_requests"}, "action": {"kind": "models", "names": ["absent"]}}
        ),
    ],
)
def test_policy_save_validates_configuration_without_a_route(policy_workspace, definition):
    cp, org_id, workspace_id = policy_workspace

    async def save():
        async with standalone_transaction(cp.db_url):
            await set_actor("root")
            await Policy(org_id=org_id, workspace_id=workspace_id, name="Invalid", definition=definition).save()

    with pytest.raises(InvalidPolicyError):
        asyncio.run(save())

    async def persisted():
        async with standalone_transaction(cp.db_url):
            return await Policy.for_workspace(workspace_id)

    assert asyncio.run(persisted()) == []
