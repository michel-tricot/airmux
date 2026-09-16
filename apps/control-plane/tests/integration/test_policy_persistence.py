from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from helpers import make_org, make_workspace, setup_control_plane

from contract import uuid7
from contract.policies import MAX_WORKSPACE_RULES, PolicyDefinition, RuleDefinition
from control_plane.db import standalone_transaction
from control_plane.models import Policy, Rule, set_actor
from control_plane.models.policy import InvalidPolicyError

if TYPE_CHECKING:
    from uuid import UUID

RULE_DEFINITION = RuleDefinition.model_validate(
    {"match": {"kind": "all_requests"}, "action": {"kind": "credential_access", "scopes": ["workspace", "org"]}}
)


def definition(rule_id: UUID) -> PolicyDefinition:
    return PolicyDefinition(target={"kind": "workspace"}, rule_ids=(rule_id,))


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
            shared_rule = await Rule(org_id=org_id, workspace_id=workspace_id, name="Shared", definition=RULE_DEFINITION).save()
            policy_definition = definition(shared_rule.id)
            for position in range(MAX_WORKSPACE_RULES - 1):
                await Policy(org_id=org_id, workspace_id=workspace_id, name=f"existing-{position}", definition=policy_definition).save()
            disabled = tuple(
                Policy(org_id=org_id, workspace_id=workspace_id, name=f"candidate-{position}", enabled=False, definition=policy_definition)
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
                        Policy(org_id=org_id, workspace_id=workspace_id, name=f"new-{position}", definition=policy_definition)
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
        assert sum(len(policy.definition.rule_ids) for policy in policies if policy.enabled) == MAX_WORKSPACE_RULES

    asyncio.run(compete())


def test_policy_save_rejects_an_unknown_rule(policy_workspace):
    cp, org_id, workspace_id = policy_workspace
    invalid_definition = definition(uuid7())

    async def save():
        async with standalone_transaction(cp.db_url):
            await set_actor("root")
            await Policy(org_id=org_id, workspace_id=workspace_id, name="Invalid", definition=invalid_definition).save()

    with pytest.raises(InvalidPolicyError):
        asyncio.run(save())

    async def persisted():
        async with standalone_transaction(cp.db_url):
            return await Policy.for_workspace(workspace_id)

    assert asyncio.run(persisted()) == []


def test_policy_save_checks_capacity_before_references(policy_workspace):
    cp, org_id, workspace_id = policy_workspace
    invalid_definition = definition(uuid7())

    async def save():
        async with standalone_transaction(cp.db_url):
            await set_actor("root")
            shared_rule = await Rule(org_id=org_id, workspace_id=workspace_id, name="Shared", definition=RULE_DEFINITION).save()
            valid_definition = definition(shared_rule.id)
            for position in range(MAX_WORKSPACE_RULES):
                await Policy(org_id=org_id, workspace_id=workspace_id, name=f"existing-{position}", definition=valid_definition).save()
            with pytest.raises(InvalidPolicyError, match=f"at most {MAX_WORKSPACE_RULES} active policy rules"):
                await Policy(org_id=org_id, workspace_id=workspace_id, name="Invalid", definition=invalid_definition).save()

    asyncio.run(save())
