from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
import respx
from conftest import make_config, make_outbox

from contract import UsageEventV1, uuid7
from data_plane.outbox import DevNullOutbox, SqliteOutbox, build_outbox


def make_event(request_id) -> UsageEventV1:
    return UsageEventV1(
        event_id=uuid4(),
        request_id=request_id,
        occurred_at=datetime.now(tz=UTC),
        org_id=uuid7(),
        workspace_id=uuid7(),
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


def test_record_roundtrips_in_order(tmp_path, http_client):
    outbox = make_outbox(tmp_path, http_client)
    events = [make_event(uuid7()), make_event(uuid7())]
    for event in events:
        outbox.record(event)
    assert outbox.next_batch(10) == events


def test_record_is_idempotent_on_event_id(tmp_path, http_client):
    outbox = make_outbox(tmp_path, http_client)
    event = make_event(uuid7())
    outbox.record(event)
    outbox.record(event)
    assert outbox.next_batch(10) == [event]


@respx.mock
async def test_flush_sends_batch_and_deletes(tmp_path, http_client):
    route = respx.post("http://cp.test/v1/events").mock(return_value=httpx.Response(200, json={"received": 2, "ingested": 2}))
    outbox = make_outbox(tmp_path, http_client)
    first, second = uuid7(), uuid7()
    outbox.record(make_event(first))
    outbox.record(make_event(second))
    assert await outbox.export_once() == 2
    assert outbox.next_batch(10) == []
    sent = json.loads(route.calls.last.request.content)
    assert [e["request_id"] for e in sent] == [str(first), str(second)]
    assert route.calls.last.request.headers["authorization"] == "Bearer dp-token"


@respx.mock
async def test_failed_flush_keeps_the_events(tmp_path, http_client):
    respx.post("http://cp.test/v1/events").mock(return_value=httpx.Response(503))
    outbox = make_outbox(tmp_path, http_client)
    event = make_event(uuid7())
    outbox.record(event)
    with pytest.raises(httpx.HTTPStatusError):
        await outbox.export_once()
    assert outbox.next_batch(10) == [event]


def test_only_one_holder_wins_the_flush_lease(tmp_path, http_client):
    a = make_outbox(tmp_path, http_client)
    b = make_outbox(tmp_path, http_client)
    a._owner = "worker-a"  # stand in for two processes on one shared cache dir
    b._owner = "worker-b"
    assert a.claim_export(ttl=30, now=1000.0) is True
    assert b.claim_export(ttl=30, now=1000.0) is False  # a still holds a live lease
    assert b.claim_export(ttl=30, now=1040.0) is True  # a's lease expired, b takes over
    assert a.claim_export(ttl=30, now=1041.0) is False


def test_build_outbox_selects_kind(tmp_path, http_client):
    config = make_config(tmp_path)
    assert isinstance(build_outbox(config.events, http_client), SqliteOutbox)
    devnull = make_config(tmp_path, outbox_kind="devnull")
    assert isinstance(build_outbox(devnull.events, http_client), DevNullOutbox)
