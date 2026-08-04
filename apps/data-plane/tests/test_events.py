from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
import respx
from conftest import make_config

from contract import UsageEventV1
from data_plane.events import flush_once
from data_plane.outbox import Outbox


def make_event(request_id: str) -> UsageEventV1:
    return UsageEventV1(
        event_id=uuid4(),
        request_id=request_id,
        occurred_at=datetime.now(tz=UTC),
        org_id="o1",
        key_id="k1",
        model_id="gpt-test",
        provider_id="openai",
        bundle_id=uuid4(),
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.000004,
        latency_ms=100,
        status="ok",
        stream=False,
    )


def test_record_roundtrips_in_order(tmp_path):
    outbox = Outbox(tmp_path)
    events = [make_event("r1"), make_event("r2")]
    for e in events:
        outbox.record(e)
    assert outbox.read_batch(10) == events
    assert outbox.pending() == 2


def test_record_is_idempotent_on_event_id(tmp_path):
    outbox = Outbox(tmp_path)
    event = make_event("r1")
    outbox.record(event)
    outbox.record(event)
    assert outbox.pending() == 1


@respx.mock
async def test_flush_sends_batch_and_deletes(tmp_path):
    route = respx.post("http://cp.test/v1/events").mock(return_value=httpx.Response(200, json={"received": 2, "ingested": 2}))
    config = make_config(tmp_path)
    outbox = Outbox(tmp_path)
    outbox.record(make_event("r1"))
    outbox.record(make_event("r2"))
    assert await flush_once(config, outbox) == 2
    assert outbox.pending() == 0
    sent = json.loads(route.calls.last.request.content)
    assert [e["request_id"] for e in sent] == ["r1", "r2"]
    assert route.calls.last.request.headers["authorization"] == "Bearer dp-token"


@respx.mock
async def test_failed_flush_keeps_the_events(tmp_path):
    respx.post("http://cp.test/v1/events").mock(return_value=httpx.Response(503))
    config = make_config(tmp_path)
    outbox = Outbox(tmp_path)
    outbox.record(make_event("r1"))
    with pytest.raises(httpx.HTTPStatusError):
        await flush_once(config, outbox)
    assert outbox.pending() == 1


def test_only_one_holder_wins_the_flush_lease(tmp_path):
    a = Outbox(tmp_path)
    b = Outbox(tmp_path)
    a._owner = "worker-a"
    b._owner = "worker-b"
    assert a.claim_flush(ttl=30, now=1000.0) is True
    assert b.claim_flush(ttl=30, now=1000.0) is False  # a still holds a live lease
    assert b.claim_flush(ttl=30, now=1040.0) is True  # a's lease expired, b takes over
    assert a.claim_flush(ttl=30, now=1041.0) is False
