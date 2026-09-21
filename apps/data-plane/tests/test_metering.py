from __future__ import annotations

import time
from decimal import Decimal

import pytest
from conftest import MODEL, ORG, PROVIDER, WORKSPACE, make_key

from contract import uuid7
from data_plane.canonical import CanonicalRequest, CanonicalResponse, CanonicalTextPart, CanonicalToolCallPart, CanonicalToolDef, CanonicalUsage
from data_plane.egress.base import Ctx
from data_plane.metering import RequestStart, cost_breakdown, denied_event, usage_event


def _model():
    return MODEL.model_copy(
        update={
            "input_price_per_mtok": Decimal(2),
            "output_price_per_mtok": Decimal(5),
            "cache_read_price_per_mtok": Decimal("0.25"),
            "cache_write_price_per_mtok": Decimal("2.5"),
        },
    )


def test_each_usage_bucket_has_a_direct_model_price():
    usage = CanonicalUsage(input_tokens=1000, output_tokens=40, cache_read_tokens=300, cache_write_tokens=200)
    cost_in, cost_out = cost_breakdown(usage, _model())
    assert cost_in == Decimal("0.001575")
    assert cost_out == Decimal("0.0002")


def test_cache_counts_cannot_make_fresh_input_negative():
    usage = CanonicalUsage(input_tokens=100, cache_read_tokens=80, cache_write_tokens=40)
    cost_in, _ = cost_breakdown(usage, _model())
    assert cost_in == Decimal("0.00012")


def test_smallest_rate_one_token_cost_is_exact():
    model = _model().model_copy(update={"input_price_per_mtok": Decimal("0.000001")})

    assert cost_breakdown(CanonicalUsage(input_tokens=1), model) == (Decimal("0.000000000001"), Decimal(0))


@pytest.mark.parametrize("estimated", [False, True])
def test_usage_has_request_attribution_and_token_source(estimated):
    bundle_id = uuid7()
    credential_id = uuid7()
    ctx = Ctx(
        request_id=uuid7(),
        model=_model(),
        provider=PROVIDER,
        stream=True,
        org_id=ORG,
        workspace_id=WORKSPACE,
        key_id=str(uuid7()),
        user_id=ORG,
        requested_model_id="gpt-test",
        requested_capabilities=frozenset(),
        credential_id=credential_id,
        credential_scope="workspace",
        bundle_id=bundle_id,
    )
    request = CanonicalRequest(
        model=MODEL.model_id,
        messages=[{"role": "user", "content": "count to three"}],
        stream=True,
        max_output_tokens=37,
    )
    response = CanonicalResponse(
        id=str(ctx.request_id),
        model=MODEL.model_id,
        content=[CanonicalTextPart(text="one two")],
        finish_reason=None,
        usage=CanonicalUsage(estimated=estimated),
    )

    event = usage_event(ctx, response, "cancelled", request)

    assert event.request_id == ctx.request_id
    assert event.bundle_id == bundle_id
    assert event.credential_id == credential_id
    assert event.credential_scope == "workspace"
    assert event.status == "cancelled"
    assert event.token_usage_source == ("estimated" if estimated else "provider")
    assert (event.input_tokens > 0) == estimated
    assert (event.output_tokens > 0) == estimated
    assert event.max_output_tokens == 37
    assert event.cost_usd == event.cost_input_usd + event.cost_output_usd


def test_estimation_preserves_reported_input_and_counts_non_text_content():
    ctx = Ctx(
        request_id=uuid7(),
        model=_model(),
        provider=PROVIDER,
        stream=True,
        org_id=ORG,
        workspace_id=WORKSPACE,
        key_id=str(uuid7()),
        user_id=ORG,
        requested_model_id="gpt-test",
        requested_capabilities=frozenset(),
        credential_id=uuid7(),
        credential_scope="workspace",
        bundle_id=uuid7(),
    )
    request = CanonicalRequest(
        model=MODEL.model_id,
        messages=[{"role": "user", "content": "use the tool"}],
        tools=[CanonicalToolDef(name="lookup", parameters={"type": "object", "properties": {"city": {"type": "string"}}})],
        stream=True,
    )
    response = CanonicalResponse(
        id=str(ctx.request_id),
        model=MODEL.model_id,
        content=[CanonicalToolCallPart(id="call-1", name="lookup", arguments='{"city":"Paris"}')],
        finish_reason=None,
        usage=CanonicalUsage(input_tokens=37, estimated=True),
    )

    event = usage_event(ctx, response, "cancelled", request)

    assert event.input_tokens == 37
    assert event.output_tokens > 0
    assert event.token_usage_source == "estimated"


def test_denial_uses_the_request_identity_and_elapsed_latency():
    request_id = uuid7()
    key = make_key("denied")[1]

    request = CanonicalRequest(model="missing", messages=[{"role": "user", "content": "hi"}])
    start = RequestStart(request_id=request_id, started_at=time.monotonic() - 1)
    event = denied_event(key, uuid7(), request, start)

    assert event.request_id == request_id
    assert event.latency_ms >= 1000
    assert event.token_usage_source == "not_applicable"
