from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from test_events import USAGE_EVENT_ADAPTER, usage_event

from contract import uuid7
from contract.budgets import OrgPolicyState, PerKeyBudgetState, PolicyStateRequest, budget_window
from contract.policies import Budget, PolicyDefinition, RuleDefinition


def test_multiple_budget_rules_share_a_policy():
    definition = PolicyDefinition.model_validate(
        {
            "target": {"kind": "workspace"},
            "rules": [
                {"match": {"kind": "all_requests"}, "action": {"kind": "budget", "amount_usd": amount, "period": period, "sharing": "shared"}}
                for amount, period in (("20", "day"), ("300", "month"))
            ],
        }
    )
    assert {rule.action.period for rule in definition.rules if isinstance(rule.action, Budget)} == {"day", "month"}


@pytest.mark.parametrize("override", [{"amount_usd": "0"}, {"amount_usd": "-1"}, {"amount_usd": 1.1}, {"period": "week"}, {"sharing": "per_user"}])
def test_budget_rejects_invalid_configuration(override):
    with pytest.raises(ValidationError):
        RuleDefinition.model_validate(
            {
                "match": {"kind": "all_requests"},
                "action": {
                    "kind": "budget",
                    "amount_usd": "100",
                    "period": "month",
                    "sharing": "shared",
                    **override,
                },
            }
        )


def test_calendar_windows_use_utc_and_real_month_boundaries():

    assert budget_window("month", datetime(2028, 2, 29, 23, tzinfo=UTC)) == (
        datetime(2028, 2, 1, tzinfo=UTC),
        datetime(2028, 3, 1, tzinfo=UTC),
    )
    assert budget_window("day", datetime(2026, 12, 31, 23, tzinfo=UTC)) == (
        datetime(2026, 12, 31, tzinfo=UTC),
        datetime(2027, 1, 1, tzinfo=UTC),
    )


@pytest.mark.parametrize(("field", "value"), [("user_id", None), ("requested_model_id", ""), ("requested_capabilities", ["unknown"])])
def test_usage_history_rejects_missing_or_invalid_request_facts(field, value):

    with pytest.raises(ValidationError):
        USAGE_EVENT_ADAPTER.validate_python(usage_event(**{field: value}))


@pytest.mark.parametrize(
    "override",
    [
        {"window_start": "2026-09-02T00:00:00Z"},
        {"window_end": "2026-10-02T00:00:00Z"},
        {"window_start": "2026-09-01T00:00:00"},
        {"exhausted_key_ids": [""]},
        {"rule_index": 100},
    ],
)
def test_budget_state_rejects_partial_windows_and_invalid_identities(override):
    with pytest.raises(ValidationError):
        PerKeyBudgetState.model_validate(
            {
                "policy_id": str(uuid7()),
                "rule_index": 0,
                "workspace_id": str(uuid7()),
                "target": {"kind": "workspace"},
                "match": {"kind": "all_requests"},
                "amount_usd": "1",
                "period": "month",
                "window_start": "2026-09-01T00:00:00Z",
                "window_end": "2026-10-01T00:00:00Z",
                "exhausted_key_ids": [],
                **override,
            }
        )


def test_policy_state_rejects_duplicate_organizations_and_rules():
    org_id = uuid7()
    with pytest.raises(ValidationError, match="Organizations must be unique"):
        PolicyStateRequest(org_ids=(org_id, org_id))
    state = PerKeyBudgetState.model_validate(
        {
            "policy_id": str(uuid7()),
            "rule_index": 0,
            "workspace_id": str(uuid7()),
            "target": {"kind": "workspace"},
            "match": {"kind": "all_requests"},
            "amount_usd": "1",
            "period": "month",
            "window_start": "2026-09-01T00:00:00Z",
            "window_end": "2026-10-01T00:00:00Z",
            "exhausted_key_ids": [],
        }
    )
    with pytest.raises(ValidationError, match="Budget rules must be unique"):
        OrgPolicyState(org_id=org_id, budgets=(state, state))
