from __future__ import annotations

import time

from conftest import MODEL, ORG, PROVIDER, WORKSPACE, make_key, make_outbox

from contract import uuid7
from data_plane.canonical import CanonicalRequest, CanonicalResponse, CanonicalTextPart, CanonicalToolCallPart, CanonicalToolDef, CanonicalUsage
from data_plane.egress.base import Ctx
from data_plane.metering import RequestStart, cost_breakdown, record_denied, record_usage


def _model():
    return MODEL.model_copy(
        update={
            "input_price_per_mtok": 2.0,
            "output_price_per_mtok": 5.0,
            "cache_read_price_per_mtok": 0.25,
            "cache_write_price_per_mtok": 2.5,
        },
    )


def test_each_usage_bucket_has_a_direct_model_price():
    usage = CanonicalUsage(input_tokens=1000, output_tokens=40, cache_read_tokens=300, cache_write_tokens=200)
    cost_in, cost_out = cost_breakdown(usage, _model())
    assert cost_in == (500 * 2.0 + 300 * 0.25 + 200 * 2.5) / 1_000_000
    assert cost_out == 40 * 5.0 / 1_000_000


def test_cache_counts_cannot_make_fresh_input_negative():
    usage = CanonicalUsage(input_tokens=100, cache_read_tokens=80, cache_write_tokens=40)
    cost_in, _ = cost_breakdown(usage, _model())
    assert cost_in == (80 * 0.25 + 40 * 2.5) / 1_000_000


def test_estimated_usage_is_persisted_with_request_attribution(tmp_path, http_client):
    outbox = make_outbox(tmp_path, http_client)
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
        credential_id=credential_id,
        credential_scope="workspace",
        bundle_id=bundle_id,
    )
    request = CanonicalRequest(model=MODEL.model_id, messages=[{"role": "user", "content": "count to three"}], stream=True)
    response = CanonicalResponse(
        id=str(ctx.request_id),
        model=MODEL.model_id,
        content=[CanonicalTextPart(text="one two")],
        finish_reason=None,
        usage=CanonicalUsage(estimated=True),
    )

    record_usage(outbox, ctx, response, "cancelled", request)
    (event,) = outbox.next_batch(10)
    outbox.close()

    assert event.request_id == ctx.request_id
    assert event.bundle_id == bundle_id
    assert event.credential_id == credential_id
    assert event.credential_scope == "workspace"
    assert event.status == "cancelled"
    assert event.input_tokens > 0
    assert event.output_tokens > 0
    assert event.cost_usd == event.cost_input_usd + event.cost_output_usd


def test_estimation_preserves_reported_input_and_counts_non_text_content(tmp_path, http_client):
    outbox = make_outbox(tmp_path, http_client)
    ctx = Ctx(
        request_id=uuid7(),
        model=_model(),
        provider=PROVIDER,
        stream=True,
        org_id=ORG,
        workspace_id=WORKSPACE,
        key_id=str(uuid7()),
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

    record_usage(outbox, ctx, response, "cancelled", request)
    (event,) = outbox.next_batch(10)

    assert event.input_tokens == 37
    assert event.output_tokens > 0


def test_denial_uses_the_request_identity_and_elapsed_latency(tmp_path, http_client):
    outbox = make_outbox(tmp_path, http_client)
    request_id = uuid7()
    key = make_key("denied")[1]

    request = CanonicalRequest(model="missing", messages=[{"role": "user", "content": "hi"}])
    start = RequestStart(request_id=request_id, started_at=time.monotonic() - 1)
    record_denied(outbox, key, uuid7(), request, start)
    (event,) = outbox.next_batch(10)

    assert event.request_id == request_id
    assert event.latency_ms >= 1000
