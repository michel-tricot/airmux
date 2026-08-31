from __future__ import annotations

from model_audit.models import Applicability, Request
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
        Filters(provider="anthropic", gateway_surfaces=("oai",)),
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
        Filters(client_mode="sdk", gateway_surfaces=("oai",)),
    )

    experiment = plan.experiments[0]
    assert experiment.direct_driver_id == "anthropic"
    assert experiment.gateway_driver_id == "openai"


def test_multiple_gateway_surfaces_expand_the_plan():
    provider_target = target(surface_id="anthropic", endpoint="messages", egress_kind="anthropic")

    plan = build_plan(
        [provider_target],
        [case()],
        {"http": frozenset({"chat/completions", "responses", "messages"})},
        Filters(gateway_surfaces=("oai", "oai_responses", "anthropic")),
    )

    assert [experiment.gateway_surface_id for experiment in plan.experiments] == ["oai", "oai_responses", "anthropic"]


def test_default_plan_compares_the_gateway_with_its_configured_upstream_surface():
    targets = [
        target(surface_id="oai", endpoint="chat/completions", egress_kind="openai_compatible", gateway_egress_kind="openai_compatible"),
        target(surface_id="oai_responses", endpoint="responses", egress_kind="openai_responses", gateway_egress_kind="openai_compatible"),
    ]

    plan = build_plan(targets, [case()], {"http": frozenset({"chat/completions", "responses"})})

    assert [experiment.target.surface_id for experiment in plan.experiments] == ["oai"]


def test_explicit_provider_surface_can_probe_a_nonconfigured_provider_surface():
    targets = [
        target(surface_id="oai", endpoint="chat/completions", egress_kind="openai_compatible", gateway_egress_kind="openai_compatible"),
        target(surface_id="oai_responses", endpoint="responses", egress_kind="openai_responses", gateway_egress_kind="openai_compatible"),
    ]

    plan = build_plan(
        targets,
        [case()],
        {"http": frozenset({"chat/completions", "responses"})},
        Filters(direct_surface="oai_responses"),
    )

    assert [experiment.target.surface_id for experiment in plan.experiments] == ["oai_responses"]


def test_plan_request_count_includes_every_scenario_step_on_both_paths():
    history = case(follow_up=Request(messages=({"role": "user", "content": "Continue"},)))
    responses = target(surface_id="oai_responses", endpoint="responses", egress_kind="openai_responses")

    plan = build_plan([responses], [history], {"http": frozenset({"responses"})})

    assert plan.requests == 4
