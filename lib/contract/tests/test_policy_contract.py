from __future__ import annotations

import pytest
from pydantic import ValidationError

from contract import uuid7
from contract.policies import Budget, PolicyDefinition, RequestMatch, RuleDefinition


@pytest.mark.parametrize(
    "match",
    [
        {"kind": "request"},
        {"kind": "request", "models": ["primary", "primary"]},
        {"kind": "request", "capabilities": ["tools", "tools"]},
        {"kind": "request", "capabilities": ["unknown"]},
        {"kind": "cel", "expression": "true"},
    ],
)
def test_invalid_request_matches_are_rejected(match):
    with pytest.raises(ValidationError):
        RuleDefinition.model_validate({"match": match, "action": {"kind": "credential_access", "scopes": ["workspace", "org"]}})


def test_request_match_combines_typed_criteria():
    definition = RuleDefinition.model_validate(
        {
            "match": {"kind": "request", "models": ["primary"], "stream": True, "capabilities": ["tools"]},
            "action": {"kind": "credential_access", "scopes": ["workspace", "org"]},
        }
    )

    assert isinstance(definition.match, RequestMatch)


@pytest.mark.parametrize(
    "action",
    [
        {"kind": "byok"},
        {"kind": "models", "names": []},
        {"kind": "providers", "names": [""]},
        {"kind": "strict_parameters", "enabled": True},
        {"kind": "price_limit", "max_input_price_per_mtok": "-1", "max_output_price_per_mtok": "2"},
        {"kind": "request_limits", "max_output_tokens": 0},
        {"kind": "credential_access", "scopes": []},
        {"kind": "credential_access", "scopes": ["org", "org"]},
        {"kind": "credential_access", "scopes": ["unknown"]},
        {"kind": "fallback", "models": ["backup"], "on": [], "max_attempts": 2, "timeout_ms": 1000},
        {"kind": "budget", "period": "day", "amount_usd": "10", "sharing": "shared", "enforcement": "placeholder"},
        {"kind": "execute", "code": "anything"},
    ],
)
def test_actions_reject_invalid_states(action):
    with pytest.raises(ValidationError):
        RuleDefinition.model_validate({"match": {"kind": "all_requests"}, "action": action})


def test_selected_keys_requires_nonempty_unique_identifiers():
    for ids in ([], [""], ["key", "key"]):
        with pytest.raises(ValidationError):
            PolicyDefinition.model_validate(
                {
                    "target": {"kind": "selected_keys", "key_ids": ids},
                    "rule_ids": [uuid7()],
                }
            )


def test_budget_has_no_enforcement_mode_until_enforcement_exists():
    definition = RuleDefinition.model_validate(
        {
            "match": {"kind": "all_requests"},
            "action": {"kind": "budget", "period": "day", "amount_usd": "10", "sharing": "shared"},
        }
    )

    assert isinstance(definition.action, Budget)


@pytest.mark.parametrize(
    "action",
    [
        {"kind": "strict_parameters"},
        {"kind": "price_limit", "max_input_price_per_mtok": "1.25", "max_output_price_per_mtok": "5"},
        {"kind": "request_limits", "max_output_tokens": 2048},
        {"kind": "credential_access", "scopes": ["workspace", "org"]},
    ],
)
def test_new_policy_actions_have_strict_valid_contracts(action):
    definition = RuleDefinition.model_validate({"match": {"kind": "all_requests"}, "action": action})

    assert definition.action.kind == action["kind"]


def test_policy_requires_rules_and_rejects_the_legacy_single_action_shape():
    with pytest.raises(ValidationError):
        PolicyDefinition.model_validate({"target": {"kind": "all_keys"}, "rule_ids": []})
    with pytest.raises(ValidationError):
        PolicyDefinition.model_validate(
            {
                "target": {"kind": "all_keys"},
                "match": {"kind": "all_requests"},
                "action": {"kind": "credential_access", "scopes": ["workspace", "org"]},
            }
        )
