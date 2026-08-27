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


def test_unrestricted_pdf_case_runs_on_every_completion_surface():
    pdf_case = case(id="modalities.pdf")
    targets = [
        target(),
        target(surface_id="oai_responses", endpoint="responses", egress_kind="openai_responses"),
        target(surface_id="anthropic", endpoint="messages", egress_kind="anthropic"),
    ]
    plan = build_plan(targets, [pdf_case], {"http": frozenset({"chat/completions", "responses", "messages"})})

    assert {experiment.target.endpoint for experiment in plan.experiments} == {"chat/completions", "responses", "messages"}
