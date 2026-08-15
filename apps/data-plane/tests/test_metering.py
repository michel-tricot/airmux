from __future__ import annotations

from uuid import UUID

from conftest import MODEL, ORG, PROVIDER, WORKSPACE

from contract import uuid7
from data_plane.canonical import CanonicalRequest, CanonicalResponse, TextPart, Usage
from data_plane.egress.base import Ctx
from data_plane.metering import cost_breakdown, record_usage
from data_plane.outbox import SqliteOutbox


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
    usage = Usage(input_tokens=1000, output_tokens=40, cache_read_tokens=300, cache_write_tokens=200)
    cost_in, cost_out = cost_breakdown(usage, _model())
    assert cost_in == (500 * 2.0 + 300 * 0.25 + 200 * 2.5) / 1_000_000
    assert cost_out == 40 * 5.0 / 1_000_000


def test_cache_counts_cannot_make_fresh_input_negative():
    usage = Usage(input_tokens=100, cache_read_tokens=80, cache_write_tokens=40)
    cost_in, _ = cost_breakdown(usage, _model())
    assert cost_in == (80 * 0.25 + 40 * 2.5) / 1_000_000


def test_estimated_usage_is_persisted_with_request_attribution(tmp_path):
    outbox = SqliteOutbox(cache_dir=tmp_path)
    bundle_id = uuid7()
    credential_id = uuid7()
    ctx = Ctx(
        request_id=str(uuid7()),
        model=_model(),
        provider=PROVIDER,
        stream=True,
        org_id=ORG,
        workspace_id=WORKSPACE,
        key_id="k1",
        credential_id=credential_id,
        credential_scope="workspace",
        bundle_id=bundle_id,
    )
    request = CanonicalRequest(model=MODEL.model_id, messages=[{"role": "user", "content": "count to three"}], stream=True)
    response = CanonicalResponse(
        id=ctx.request_id,
        model=MODEL.model_id,
        content=[TextPart(text="one two")],
        finish_reason=None,
        usage=Usage(estimated=True),
    )

    record_usage(outbox, ctx, response, "cancelled", request)
    (event,) = outbox.next_batch(10)
    outbox.close()

    assert event.request_id == UUID(ctx.request_id)
    assert event.bundle_id == bundle_id
    assert event.credential_id == credential_id
    assert event.credential_scope == "workspace"
    assert event.status == "cancelled"
    assert event.input_tokens > 0
    assert event.output_tokens > 0
    assert event.cost_usd == event.cost_input_usd + event.cost_output_usd
