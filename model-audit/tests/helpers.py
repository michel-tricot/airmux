from __future__ import annotations

from model_audit.models import Case, Claim, Oracle, Request, Target


def target(**changes: object) -> Target:
    return Target(
        provider_id="stub",
        surface_id="oai",
        endpoint="chat/completions",
        egress_kind="openai_compatible",
        base_url="https://provider.example/v1",
        credential_env="STUB_API_KEY",
        auth="bearer",
        headers={},
        model_id="stub/model",
        upstream_model="model",
        context_window=8192,
        max_output_tokens=1024,
    ).model_copy(update=changes)


def case(**changes: object) -> Case:
    return Case(
        id="text.basic",
        title="Basic text",
        claims=(Claim(dimension="capability", name="text_generation"),),
        request=Request(messages=({"role": "user", "content": "Reply with ok"},)),
        oracle=Oracle(text_contains="ok"),
    ).model_copy(update=changes)
