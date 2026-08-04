from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
import respx

from contract import UsageEventV1
from data_plane.config import AuthConfig, BundleConfig, Config, ControlPlaneLink
from data_plane.events import buffer_event, flush_once, read_buffered_events


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


def make_config(tmp_path) -> Config:
    return Config(
        control_plane=ControlPlaneLink(url="http://cp.test", token="dp-token"),  # noqa: S106 test fixture, not a secret
        bundle=BundleConfig(public_key="unused", cache_dir=tmp_path),
        auth=AuthConfig(token_public_key="unused"),  # noqa: S106 a public key, not a secret
    )


def test_buffer_survives_and_roundtrips(tmp_path):
    events = [make_event("r1"), make_event("r2")]
    for e in events:
        buffer_event(tmp_path, e)
    assert read_buffered_events(tmp_path) == events


@respx.mock
async def test_flush_sends_batch_and_truncates(tmp_path):
    route = respx.post("http://cp.test/v1/events").mock(return_value=httpx.Response(200, json={"received": 2, "ingested": 2}))
    config = make_config(tmp_path)
    buffer_event(tmp_path, make_event("r1"))
    buffer_event(tmp_path, make_event("r2"))
    assert await flush_once(config) == 2
    assert read_buffered_events(tmp_path) == []
    sent = json.loads(route.calls.last.request.content)
    assert [e["request_id"] for e in sent] == ["r1", "r2"]
    assert route.calls.last.request.headers["authorization"] == "Bearer dp-token"


@respx.mock
async def test_failed_flush_keeps_the_buffer(tmp_path):
    respx.post("http://cp.test/v1/events").mock(return_value=httpx.Response(503))
    config = make_config(tmp_path)
    buffer_event(tmp_path, make_event("r1"))
    with pytest.raises(httpx.HTTPStatusError):
        await flush_once(config)
    assert len(read_buffered_events(tmp_path)) == 1


@respx.mock
async def test_torn_final_line_is_dropped_and_flush_proceeds(tmp_path):
    respx.post("http://cp.test/v1/events").mock(return_value=httpx.Response(200, json={}))
    config = make_config(tmp_path)
    buffer_event(tmp_path, make_event("r1"))
    with (tmp_path / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write('{"event_id": "torn-mid-wr')
    assert await flush_once(config) == 1
    assert read_buffered_events(tmp_path) == []


@respx.mock
async def test_corrupt_middle_line_quarantines_buffer(tmp_path):
    respx.post("http://cp.test/v1/events").mock(return_value=httpx.Response(200, json={}))
    config = make_config(tmp_path)
    buffer_event(tmp_path, make_event("r1"))
    with (tmp_path / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write("garbage\n")
    buffer_event(tmp_path, make_event("r2"))
    assert await flush_once(config) == 0
    assert (tmp_path / "events.jsonl.corrupt").exists()
    assert not (tmp_path / "events.jsonl").exists()
