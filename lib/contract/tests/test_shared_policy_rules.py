from __future__ import annotations

import pytest
from pydantic import ValidationError

from contract.policies import PolicyDefinition


def test_policy_rules_are_nonempty_canonical_and_unique():
    models = {"match": {"kind": "all_requests"}, "action": {"kind": "models", "names": ["primary"]}}
    providers = {"match": {"kind": "all_requests"}, "action": {"kind": "providers", "names": ["openai"]}}
    definition = PolicyDefinition.model_validate({"target": {"kind": "workspace"}, "rules": [providers, models]})

    assert definition == PolicyDefinition.model_validate({"target": {"kind": "workspace"}, "rules": [models, providers]})
    for rules in ([], [models, models]):
        with pytest.raises(ValidationError):
            PolicyDefinition.model_validate({"target": {"kind": "workspace"}, "rules": rules})


def test_policy_rejects_multiple_fallback_rules():
    fallback = {
        "match": {"kind": "all_requests"},
        "action": {"kind": "fallback", "models": ["backup"], "on": ["timeout"], "max_attempts": 2, "timeout_ms": 1000},
    }
    second = {
        "match": {"kind": "request", "models": ["primary"]},
        "action": {"kind": "fallback", "models": ["backup"], "on": ["timeout"], "max_attempts": 2, "timeout_ms": 1000},
    }

    with pytest.raises(ValidationError, match="at most one fallback rule"):
        PolicyDefinition.model_validate({"target": {"kind": "workspace"}, "rules": [fallback, second]})
