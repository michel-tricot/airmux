from __future__ import annotations

import pytest
from pydantic import ValidationError

from contract import uuid7
from contract.policies import PolicyDefinition, RuleEntry


def test_two_policies_can_reference_one_rule():
    workspace_id = uuid7()
    rule = RuleEntry.model_validate(
        {
            "id": uuid7(),
            "workspace_id": workspace_id,
            "name": "Team credentials",
            "definition": {
                "match": {"kind": "all_requests"},
                "action": {"kind": "credential_access", "scopes": ["workspace", "org"]},
            },
        }
    )

    first = PolicyDefinition.model_validate({"target": {"kind": "all_keys"}, "rule_ids": [rule.id]})
    second = PolicyDefinition.model_validate({"target": {"kind": "selected_keys", "key_ids": ["customer"]}, "rule_ids": [rule.id]})

    assert first.rule_ids == second.rule_ids == (rule.id,)


def test_policy_rule_references_are_nonempty_ordered_and_unique():
    first = uuid7()
    second = uuid7()
    definition = PolicyDefinition.model_validate({"target": {"kind": "all_keys"}, "rule_ids": [second, first]})

    assert definition.rule_ids == (second, first)
    for rule_ids in ([], [first, first]):
        with pytest.raises(ValidationError):
            PolicyDefinition.model_validate({"target": {"kind": "all_keys"}, "rule_ids": rule_ids})
