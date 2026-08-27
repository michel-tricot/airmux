from __future__ import annotations

from model_audit.models import Applicability
from model_audit.plan import Filters, build_plan
from tests.helpers import case, target


def test_plan_runs_claims_without_consulting_existing_support_metadata():
    experiment_case = case()

    plan = build_plan([target()], [experiment_case], {"http": frozenset({"chat/completions"})})

    assert [(experiment.case.id, experiment.driver_id) for experiment in plan.experiments] == [("text.basic", "http")]


def test_plan_uses_surface_applicability_and_filters_only():
    responses_only = case(applies_to=Applicability(endpoints=frozenset({"responses"})))

    plan = build_plan([target()], [responses_only], {"http": frozenset({"chat/completions", "responses"})}, Filters(provider="stub"))

    assert plan.experiments == ()


def test_sdk_selection_uses_the_vendor_family_driver():
    plan = build_plan(
        [target(surface_id="anthropic", endpoint="messages", egress_kind="anthropic")],
        [case()],
        {"anthropic": frozenset({"messages"})},
        Filters(client_mode="sdk"),
    )

    assert [experiment.driver_id for experiment in plan.experiments] == ["anthropic"]
