from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
import respx
from conftest import make_config

from contract import UsageEventV1, uuid7
from data_plane.config import ControlPlaneLink
from data_plane.outbox import DevNullOutbox, EventExporter, SqliteOutbox, build_exporter, build_outbox


def make_outbox(tmp_path) -> SqliteOutbox:
    return SqliteOutbox(cache_dir=tmp_path)


def make_exporter(tmp_path, http_client, flush_interval_s=5.0) -> tuple[SqliteOutbox, EventExporter]:
    outbox = make_outbox(tmp_path)
    return outbox, EventExporter(
        outbox=outbox,
        control_plane_url="http://cp.test",
        control_plane_token="dp-token",
        flush_interval_s=flush_interval_s,
        http_client=http_client,
    )


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


def test_record_roundtrips_in_order(tmp_path):
    outbox = make_outbox(tmp_path)
    events = [make_event(uuid7()), make_event(uuid7())]
    for event in events:
        outbox.record(event)
    assert outbox.next_batch(10) == events


def test_record_is_idempotent_on_event_id(tmp_path):
    outbox = make_outbox(tmp_path)
    event = make_event(uuid7())
    outbox.record(event)
    outbox.record(event)
    assert outbox.next_batch(10) == [event]


@respx.mock
async def test_flush_sends_batch_and_deletes(tmp_path, http_client):
    route = respx.post("http://cp.test/v1/events").mock(return_value=httpx.Response(200, json={"received": 2, "ingested": 2}))
    outbox, exporter = make_exporter(tmp_path, http_client)
    first, second = uuid7(), uuid7()
    outbox.record(make_event(first))
    outbox.record(make_event(second))
    assert await exporter.once() == 2
    assert outbox.next_batch(10) == []
    sent = json.loads(route.calls.last.request.content)
    assert [e["request_id"] for e in sent] == [str(first), str(second)]
    assert route.calls.last.request.headers["authorization"] == "Bearer dp-token"


@respx.mock
async def test_failed_flush_keeps_the_events(tmp_path, http_client):
    respx.post("http://cp.test/v1/events").mock(return_value=httpx.Response(503))
    outbox, exporter = make_exporter(tmp_path, http_client)
    event = make_event(uuid7())
    outbox.record(event)
    with pytest.raises(httpx.HTTPStatusError):
        await exporter.once()
    assert outbox.next_batch(10) == [event]


def test_only_one_holder_wins_the_flush_lease(tmp_path):
    a = make_outbox(tmp_path)
    b = make_outbox(tmp_path)
    a._owner = "worker-a"  # stand in for two processes on one shared cache dir
    b._owner = "worker-b"
    assert a.claim_export(ttl=30, now=1000.0) is True
    assert b.claim_export(ttl=30, now=1000.0) is False  # a still holds a live lease
    assert b.claim_export(ttl=30, now=1040.0) is True  # a's lease expired, b takes over
    assert a.claim_export(ttl=30, now=1041.0) is False


def test_build_outbox_selects_backend_without_a_transport(tmp_path):
    assert isinstance(build_outbox(make_config(tmp_path).events), SqliteOutbox)
    assert isinstance(build_outbox(make_config(tmp_path, backend="devnull").events), DevNullOutbox)


def test_build_exporter_requires_both_persistence_and_a_control_plane(tmp_path, http_client):
    config = make_config(tmp_path)
    outbox = build_outbox(config.events)
    assert isinstance(build_exporter(outbox, config.control_plane, config.events, http_client), EventExporter)
    assert build_exporter(DevNullOutbox(), config.control_plane, config.events, http_client) is None
    assert build_exporter(outbox, ControlPlaneLink(), config.events, http_client) is None
