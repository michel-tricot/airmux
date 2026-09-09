from __future__ import annotations

import pytest
from pydantic import ValidationError

from contract.policies import PolicyDefinition, compile_condition


@pytest.mark.parametrize("condition", ["unknown == 1", "42", "request_stream + 1", "[1, 2].exists(x, x > 0)"])
def test_invalid_conditions_are_rejected(condition):
    with pytest.raises(ValueError, match=r"policy condition|Policy conditions"):
        compile_condition(condition)


def test_condition_is_compiled_and_evaluated_against_explicit_facts():
    condition = compile_condition('request_model == "primary" && !request_stream')
    assert condition.eval(data={"request_model": "primary", "request_stream": False}).value() is True
    assert condition.eval(data={"request_model": "backup", "request_stream": False}).value() is False


@pytest.mark.parametrize(
    "action",
    [
        {"kind": "models", "names": []},
        {"kind": "providers", "names": [""]},
        {"kind": "fallback", "models": ["backup"], "on": [], "max_attempts": 2, "timeout_ms": 1000},
        {"kind": "budget", "period": "day", "amount_usd": "10", "sharing": "shared", "enforcement": "enforced"},
        {"kind": "execute", "code": "anything"},
    ],
)
def test_actions_reject_invalid_states(action):
    with pytest.raises(ValidationError):
        PolicyDefinition.model_validate({"target": {"kind": "all_keys"}, "condition": "true", "action": action})


def test_selected_keys_requires_nonempty_unique_identifiers():
    for ids in ([], [""], ["key", "key"]):
        with pytest.raises(ValidationError):
            PolicyDefinition.model_validate({"target": {"kind": "selected_keys", "key_ids": ids}, "condition": "true", "action": {"kind": "byok"}})
