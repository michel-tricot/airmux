from __future__ import annotations

import pytest
from pydantic import ValidationError

from contract.policies import Budget, PolicyDefinition, RequestMatch


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
        PolicyDefinition.model_validate({"target": {"kind": "all_keys"}, "match": match, "action": {"kind": "byok"}})


def test_request_match_combines_typed_criteria():
    definition = PolicyDefinition.model_validate(
        {
            "target": {"kind": "all_keys"},
            "match": {"kind": "request", "models": ["primary"], "stream": True, "capabilities": ["tools"]},
            "action": {"kind": "byok"},
        }
    )

    assert isinstance(definition.match, RequestMatch)


@pytest.mark.parametrize(
    "action",
    [
        {"kind": "models", "names": []},
        {"kind": "providers", "names": [""]},
        {"kind": "fallback", "models": ["backup"], "on": [], "max_attempts": 2, "timeout_ms": 1000},
        {"kind": "budget", "period": "day", "amount_usd": "10", "sharing": "shared", "enforcement": "placeholder"},
        {"kind": "execute", "code": "anything"},
    ],
)
def test_actions_reject_invalid_states(action):
    with pytest.raises(ValidationError):
        PolicyDefinition.model_validate({"target": {"kind": "all_keys"}, "match": {"kind": "all_requests"}, "action": action})


def test_selected_keys_requires_nonempty_unique_identifiers():
    for ids in ([], [""], ["key", "key"]):
        with pytest.raises(ValidationError):
            PolicyDefinition.model_validate(
                {"target": {"kind": "selected_keys", "key_ids": ids}, "match": {"kind": "all_requests"}, "action": {"kind": "byok"}}
            )


def test_budget_has_no_enforcement_mode_until_enforcement_exists():
    definition = PolicyDefinition.model_validate(
        {
            "target": {"kind": "all_keys"},
            "match": {"kind": "all_requests"},
            "action": {"kind": "budget", "period": "day", "amount_usd": "10", "sharing": "shared"},
        }
    )

    assert isinstance(definition.action, Budget)
