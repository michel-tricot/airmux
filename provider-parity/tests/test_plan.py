from __future__ import annotations

from provider_parity.models import Case, Oracle, Request, Requirements, Target
from provider_parity.plan import Filters, build_plan

TARGET = Target(
    provider_id="openai",
    surface_id="oai",
    endpoint="chat/completions",
    egress_kind="openai_compatible",
    base_url="https://api.openai.com/v1",
    credential_env="OPENAI_API_KEY",
    auth="bearer",
    headers={},
    model_id="openai/gpt-test",
    upstream_model="gpt-test",
    context_window=128000,
    max_output_tokens=4096,
    input_modalities=frozenset({"text"}),
    capabilities=frozenset({"streaming", "tools"}),
    parameter_support={"temperature": "supported"},
)
TEXT = Case(
    id="text.basic", title="Basic text", request=Request(messages=({"role": "user", "content": "Say ok"},)), oracle=Oracle(text_nonempty=True)
)
TOOLS = Case(
    id="tools.single",
    title="Tool",
    requires=Requirements(capabilities=frozenset({"tools"})),
    request=Request(messages=({"role": "user", "content": "Use a tool"},)),
    oracle=Oracle(tool_names=("report_result",)),
)
REASONING = Case(
    id="reasoning.exposed",
    title="Reasoning",
    requires=Requirements(capabilities=frozenset({"reasoning"})),
    request=Request(messages=({"role": "user", "content": "Think"},)),
    oracle=Oracle(reasoning_present=True),
)


def test_plan_is_the_supported_cross_product_and_is_filterable():
    plan = build_plan([TARGET], [TEXT, TOOLS, REASONING], {"openai": frozenset({"chat/completions"})}, Filters(provider="openai"))

    assert [(experiment.case.id, experiment.transport) for experiment in plan.experiments] == [
        ("text.basic", "buffered"),
        ("tools.single", "buffered"),
    ]
    assert plan.skipped == 1


def test_streamed_variants_require_model_streaming_support():
    streamed = TEXT.model_copy(update={"transports": ("buffered", "streamed")})
    plan = build_plan([TARGET], [streamed], {"openai": frozenset({"chat/completions"})}, Filters(model="openai/gpt-test"))

    assert [experiment.transport for experiment in plan.experiments] == ["buffered", "streamed"]
