from __future__ import annotations

from model_audit.models import Applicability
from model_audit.plan import Filters, build_plan
from tests.helpers import case, target


def test_plan_runs_claims_without_consulting_existing_support_metadata():
    experiment_case = case()

    plan = build_plan([target()], [experiment_case], {"http": frozenset({"chat/completions"})})

    assert [(experiment.case.id, experiment.direct_driver_id, experiment.gateway_driver_id) for experiment in plan.experiments] == [
        ("text.basic", "http", "http")
    ]


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

    assert [(experiment.direct_driver_id, experiment.gateway_driver_id) for experiment in plan.experiments] == [("anthropic", "anthropic")]


def test_unrestricted_pdf_case_runs_on_every_completion_surface():
    pdf_case = case(id="modalities.pdf")
    targets = [
        target(),
        target(surface_id="oai_responses", endpoint="responses", egress_kind="openai_responses"),
        target(surface_id="anthropic", endpoint="messages", egress_kind="anthropic"),
    ]
    plan = build_plan(targets, [pdf_case], {"http": frozenset({"chat/completions", "responses", "messages"})})

    assert {experiment.target.endpoint for experiment in plan.experiments} == {"chat/completions", "responses", "messages"}


def test_case_namespace_selects_every_case_in_the_group():
    cases = [case(id="modalities.image"), case(id="modalities.pdf"), case(id="text.basic")]

    plan = build_plan([target()], cases, {"http": frozenset({"chat/completions"})}, Filters(cases=("modalities",)))

    assert [experiment.case.id for experiment in plan.experiments] == ["modalities.image", "modalities.pdf"]


def test_repeated_case_selectors_are_combined():
    cases = [case(id="modalities.image"), case(id="modalities.pdf"), case(id="text.basic")]

    plan = build_plan(
        [target()],
        cases,
        {"http": frozenset({"chat/completions"})},
        Filters(cases=("modalities.image", "text.basic")),
    )

    assert [experiment.case.id for experiment in plan.experiments] == ["modalities.image", "text.basic"]


def test_provider_selection_includes_every_model_from_that_provider():
    targets = [
        target(provider_id="anthropic", model_id="anthropic/claude-a"),
        target(provider_id="anthropic", model_id="anthropic/claude-b"),
        target(provider_id="openai", model_id="openai/gpt-a"),
    ]

    plan = build_plan(targets, [case()], {"http": frozenset({"chat/completions"})}, Filters(provider="anthropic"))

    assert [experiment.target.model_id for experiment in plan.experiments] == ["anthropic/claude-a", "anthropic/claude-b"]


def test_gateway_surface_is_independent_from_the_provider_surface():
    provider_target = target(
        provider_id="anthropic",
        model_id="anthropic/claude-a",
        surface_id="anthropic",
        endpoint="messages",
        egress_kind="anthropic",
    )

    plan = build_plan(
        [provider_target],
        [case()],
        {"http": frozenset({"chat/completions", "messages"})},
        Filters(provider="anthropic", gateway_surface="oai"),
    )

    experiment = plan.experiments[0]
    assert experiment.target.surface_id == "anthropic"
    assert experiment.target.endpoint == "messages"
    assert experiment.gateway_surface_id == "oai"
    assert experiment.gateway_endpoint == "chat/completions"


def test_sdk_cross_surface_uses_each_dialects_vendor_driver():
    provider_target = target(surface_id="anthropic", endpoint="messages", egress_kind="anthropic")

    plan = build_plan(
        [provider_target],
        [case()],
        {"anthropic": frozenset({"messages"}), "openai": frozenset({"chat/completions", "responses"})},
        Filters(client_mode="sdk", gateway_surface="oai"),
    )

    experiment = plan.experiments[0]
    assert experiment.direct_driver_id == "anthropic"
    assert experiment.gateway_driver_id == "openai"
