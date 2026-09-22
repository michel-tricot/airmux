from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import aiohttp
import pytest
from conftest import CTX, ORG, TEXT_LOG, WORKSPACE, make_adapter, make_outbox, mock_control_plane, sse
from starlette.requests import ClientDisconnect
from starlette.responses import Response, StreamingResponse
from starlette.testclient import TestClient

from contract import uuid7
from data_plane.canonical import CanonicalRequest
from data_plane.egress.base import Ctx, UpstreamRequest
from data_plane.ingress import REGISTRY as INGRESS
from data_plane.metrics import DataPlaneMetrics
from data_plane.streaming import StreamSession

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from data_plane.outbox import SqliteOutbox

UPSTREAM = UpstreamRequest(method="POST", url="https://api.openai.com/v1/chat/completions", headers={}, body=b"{}")
REQUEST = CanonicalRequest(model="gpt-test", messages=[{"role": "user", "content": "hi"}], stream=True)


@pytest.fixture
async def metering(tmp_path, http_client) -> AsyncGenerator[tuple[Ctx, SqliteOutbox]]:
    outbox = make_outbox(tmp_path, http_client)
    ctx = replace(
        CTX,
        request_id=uuid7(),
        org_id=ORG,
        workspace_id=WORKSPACE,
        key_id=str(uuid7()),
        credential_id=uuid7(),
        credential_scope="workspace",
        bundle_id=uuid7(),
    )
    yield ctx, outbox
    await outbox.close()


async def _event(outbox: SqliteOutbox):
    (event,) = await outbox.next_batch(10)
    return event


def test_streaming_end_to_end(http_mock, api_key, dp_app):
    http_mock.post("https://api.openai.com/v1/chat/completions", status=200, body=TEXT_LOG, repeat=True)
    mock_control_plane(http_mock)
    with (
        TestClient(dp_app) as client,
        client.stream(
            "POST",
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}], "stream": True},
        ) as r,
    ):
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = b"".join(r.iter_bytes())
    text_body = body.decode()
    events = [json.loads(line[6:]) for line in text_body.splitlines() if line.startswith("data: ") and line != "data: [DONE]"]
    text = "".join(e["choices"][0]["delta"].get("content", "") for e in events if e["choices"])
    assert text == "héllo \U0001f30d world"
    assert events[-1]["usage"] == {
        "prompt_tokens": 5,
        "completion_tokens": 7,
        "total_tokens": 12,
        "prompt_tokens_details": {"cached_tokens": 0},
    }
    assert text_body.rstrip().endswith("data: [DONE]")


def test_streaming_upstream_error_status_passes_through(http_mock, api_key, dp_app):
    http_mock.post("https://api.openai.com/v1/chat/completions", status=429, payload={"error": {"code": "rate_limited"}}, repeat=True)
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        r = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}], "stream": True},
        )
    assert r.status_code == 429


def _body_gen(response: object) -> AsyncGenerator[bytes]:
    assert isinstance(response, StreamingResponse)
    return cast("AsyncGenerator[bytes]", response.body_iterator)


async def _open_stream(
    ctx: Ctx,
    request: CanonicalRequest,
    outbox: SqliteOutbox,
    http_client: aiohttp.ClientSession,
    metrics: DataPlaneMetrics | None = None,
) -> Response:
    with outbox.reserve() as reservation:
        session = StreamSession(
            adapter=make_adapter(),
            ingress=INGRESS["openai_chat_completions"],
            ctx=ctx,
            request=request,
            adjustments=(),
            reservation=reservation,
            http_client=http_client,
            metrics=metrics or DataPlaneMetrics(),
            egress_kind="openai_compatible",
            attempt_started_at=time.monotonic(),
        )
        return await session.open(UPSTREAM)


async def test_cancellation_estimates_partial_tokens(http_mock, metering, http_client):
    ctx, outbox = metering
    http_mock.post("https://api.openai.com/v1/chat/completions", status=200, body=TEXT_LOG, repeat=True)
    req = CanonicalRequest(model="gpt-test", messages=[{"role": "user", "content": "count to three"}], stream=True)
    iterator = _body_gen(await _open_stream(ctx, req, outbox, http_client))
    await anext(iterator)
    await anext(iterator)
    with pytest.raises(asyncio.CancelledError):
        await iterator.athrow(asyncio.CancelledError())
    event = await _event(outbox)
    assert event.status == "cancelled"
    assert event.input_tokens > 0
    assert event.output_tokens > 0
    assert event.cost_usd > 0


async def test_disconnect_before_first_body_releases_stream_resources(monkeypatch, metering, http_client):
    ctx, outbox = metering

    class FakeResponse:
        status = 200

    class FakeStream:
        exited = False

        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, *_args):
            self.exited = True

    stream = FakeStream()
    monkeypatch.setattr(http_client, "request", lambda *_args, **_kwargs: stream)
    response = await _open_stream(ctx, REQUEST, outbox, http_client)

    async def receive():
        return {"type": "http.disconnect"}

    async def send(_message):
        raise OSError

    with pytest.raises(ClientDisconnect):
        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)

    assert stream.exited
    assert (await outbox.stats())["reserved"] == 0
    assert (await _event(outbox)).status == "cancelled"


async def test_mid_stream_error_event_becomes_sse_error(http_mock, metering, http_client):
    ctx, outbox = metering
    metrics = DataPlaneMetrics()
    hi = {"id": "cmpl-9", "model": "gpt-real", "choices": [{"index": 0, "delta": {"content": "héllo "}, "finish_reason": None}]}
    log = sse(hi) + sse({"error": {"code": "overloaded", "message": "try later"}})
    http_mock.post("https://api.openai.com/v1/chat/completions", status=200, body=log, repeat=True)
    chunks = [chunk async for chunk in _body_gen(await _open_stream(ctx, REQUEST, outbox, http_client, metrics))]
    assert any(json.loads(chunk[6:]).get("error", {}).get("code") == "overloaded" for chunk in chunks if chunk != b"data: [DONE]\n\n")
    assert (await _event(outbox)).status == "upstream_error"
    assert 'airmux_data_plane_upstream_attempts_total{egress_kind="openai_compatible",outcome="provider_error"} 1.0' in metrics.render().decode()


async def test_stream_ending_before_the_provider_terminal_becomes_sse_error(http_mock, metering, http_client):
    ctx, outbox = metering
    incomplete = TEXT_LOG.removesuffix(b"data: [DONE]\n\n")
    http_mock.post("https://api.openai.com/v1/chat/completions", status=200, body=incomplete, repeat=True)
    chunks = [chunk async for chunk in _body_gen(await _open_stream(ctx, REQUEST, outbox, http_client))]
    assert any(json.loads(chunk[6:]).get("error", {}).get("code") == "invalid_upstream_response" for chunk in chunks if chunk != b"data: [DONE]\n\n")
    assert (await _event(outbox)).status == "upstream_error"


async def test_malformed_stream_event_becomes_sse_error(http_mock, metering, http_client):
    ctx, outbox = metering
    http_mock.post("https://api.openai.com/v1/chat/completions", status=200, body=b"data: not-json\n\n", repeat=True)
    chunks = [chunk async for chunk in _body_gen(await _open_stream(ctx, REQUEST, outbox, http_client))]
    assert any(json.loads(chunk[6:]).get("error", {}).get("code") == "invalid_upstream_response" for chunk in chunks if chunk != b"data: [DONE]\n\n")
    assert (await _event(outbox)).status == "upstream_error"


async def test_error_body_read_failure_closes_upstream_and_propagates(monkeypatch, metering, http_client):
    ctx, outbox = metering

    class FakeResp:
        status = 502

        async def read(self):
            msg = "connection reset while reading error body"
            raise aiohttp.ClientPayloadError(msg)

    class FakeStreamCM:
        def __init__(self):
            self.exited = False

        async def __aenter__(self):
            return FakeResp()

        async def __aexit__(self, *args):
            self.exited = True

    cm = FakeStreamCM()

    class FakeClient:
        def request(self, *args, **kwargs):
            return cm

    monkeypatch.setattr(http_client, "request", FakeClient().request)
    with pytest.raises(aiohttp.ClientPayloadError, match="connection reset"):
        await _open_stream(ctx, REQUEST, outbox, http_client)
    assert cm.exited
