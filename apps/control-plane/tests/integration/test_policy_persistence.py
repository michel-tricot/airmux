from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from helpers import make_org, make_workspace, setup_control_plane

from contract.policies import MAX_WORKSPACE_RULES, PolicyDefinition, RuleDefinition
from control_plane.db import standalone_transaction
from control_plane.models import Policy, set_actor
from control_plane.models.policy import InvalidPolicyError

RULE_DEFINITION = RuleDefinition.model_validate(
    {"match": {"kind": "all_requests"}, "action": {"kind": "credential_access", "scopes": ["workspace", "org"]}}
)
LIMIT_RULE_DEFINITION = RuleDefinition.model_validate(
    {"match": {"kind": "all_requests"}, "action": {"kind": "request_limits", "max_output_tokens": 1}}
)


def definition(rule: RuleDefinition = RULE_DEFINITION) -> PolicyDefinition:
    return PolicyDefinition(target={"kind": "workspace"}, rules=(rule,))


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
            policy_definition = definition()
            existing_count = MAX_WORKSPACE_RULES - (1 if operation == "create" else 2)
            for position in range(existing_count):
                existing_definition = (
                    PolicyDefinition(target={"kind": "workspace"}, rules=(RULE_DEFINITION, LIMIT_RULE_DEFINITION))
                    if operation == "enable" and position == 0
                    else policy_definition
                )
                await Policy(org_id=org_id, workspace_id=workspace_id, name=f"existing-{position}", definition=existing_definition).save()
            disabled = (
                tuple(
                    Policy(org_id=org_id, workspace_id=workspace_id, name=f"candidate-{position}", enabled=False, definition=policy_definition)
                    for position in range(2)
                )
                if operation == "enable"
                else ()
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
        assert sum(len(policy.definition.rules) for policy in policies if policy.enabled) == MAX_WORKSPACE_RULES

    asyncio.run(compete())


def test_policy_save_rejects_an_unknown_model(policy_workspace):
    cp, org_id, workspace_id = policy_workspace
    invalid_definition = definition(
        RuleDefinition.model_validate({"match": {"kind": "request", "models": ["unknown"]}, "action": {"kind": "models", "names": ["unknown"]}})
    )

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


def test_policy_save_checks_capacity_before_catalog_references(policy_workspace):
    cp, org_id, workspace_id = policy_workspace
    invalid_definition = definition(
        RuleDefinition.model_validate({"match": {"kind": "request", "models": ["unknown"]}, "action": {"kind": "models", "names": ["unknown"]}})
    )

    async def save():
        async with standalone_transaction(cp.db_url):
            await set_actor("root")
            valid_definition = definition()
            two_rules = PolicyDefinition(target={"kind": "workspace"}, rules=(RULE_DEFINITION, LIMIT_RULE_DEFINITION))
            await Policy(org_id=org_id, workspace_id=workspace_id, name="existing-0", definition=two_rules).save()
            for position in range(1, MAX_WORKSPACE_RULES - 1):
                await Policy(org_id=org_id, workspace_id=workspace_id, name=f"existing-{position}", definition=valid_definition).save()
            with pytest.raises(InvalidPolicyError, match=f"at most {MAX_WORKSPACE_RULES} active policy rules"):
                await Policy(org_id=org_id, workspace_id=workspace_id, name="Invalid", definition=invalid_definition).save()

    asyncio.run(save())
