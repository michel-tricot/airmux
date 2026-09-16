from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import httpx
import pytest
import respx
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


@respx.mock
def test_streaming_end_to_end(api_key, dp_app):
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, content=TEXT_LOG))
    mock_control_plane()
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


@respx.mock
def test_streaming_upstream_error_status_passes_through(api_key, dp_app):
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(429, json={"error": {"code": "rate_limited"}}))
    mock_control_plane()
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


async def _open_stream(ctx: Ctx, request: CanonicalRequest, outbox: SqliteOutbox, http_client: httpx.AsyncClient) -> Response:
    with outbox.reserve() as reservation:
        session = StreamSession(
            adapter=make_adapter(),
            ingress=INGRESS["openai_chat_completions"],
            ctx=ctx,
            request=request,
            adjustments=(),
            reservation=reservation,
            http_client=http_client,
            metrics=DataPlaneMetrics(),
            egress_kind="openai_compatible",
            attempt_started_at=time.monotonic(),
        )
        return await session.open(UPSTREAM)


@respx.mock
async def test_cancellation_estimates_partial_tokens(metering, http_client):
    ctx, outbox = metering
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, content=TEXT_LOG))
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
        is_error = False

    class FakeStream:
        exited = False

        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, *_args):
            self.exited = True

    stream = FakeStream()
    monkeypatch.setattr(http_client, "stream", lambda *_args, **_kwargs: stream)
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


@respx.mock
async def test_mid_stream_error_event_becomes_sse_error(metering, http_client):
    ctx, outbox = metering
    hi = {"id": "cmpl-9", "model": "gpt-real", "choices": [{"index": 0, "delta": {"content": "héllo "}, "finish_reason": None}]}
    log = sse(hi) + sse({"error": {"code": "overloaded", "message": "try later"}})
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, content=log))
    chunks = [chunk async for chunk in _body_gen(await _open_stream(ctx, REQUEST, outbox, http_client))]
    assert any(b'"code": "overloaded"' in c for c in chunks)
    assert (await _event(outbox)).status == "upstream_error"


@respx.mock
async def test_stream_ending_before_the_provider_terminal_becomes_sse_error(metering, http_client):
    ctx, outbox = metering
    incomplete = TEXT_LOG.removesuffix(b"data: [DONE]\n\n")
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, content=incomplete))
    chunks = [chunk async for chunk in _body_gen(await _open_stream(ctx, REQUEST, outbox, http_client))]
    assert any(b'"code": "invalid_upstream_response"' in chunk for chunk in chunks)
    assert (await _event(outbox)).status == "upstream_error"


@respx.mock
async def test_malformed_stream_event_becomes_sse_error(metering, http_client):
    ctx, outbox = metering
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, content=b"data: not-json\n\n"))
    chunks = [chunk async for chunk in _body_gen(await _open_stream(ctx, REQUEST, outbox, http_client))]
    assert any(b'"code": "invalid_upstream_response"' in chunk for chunk in chunks)
    assert (await _event(outbox)).status == "upstream_error"


async def test_error_body_read_failure_closes_upstream_and_propagates(monkeypatch, metering, http_client):
    ctx, outbox = metering

    class FakeResp:
        is_error = True

        async def aread(self):
            msg = "connection reset while reading error body"
            raise httpx.ReadError(msg)

    class FakeStreamCM:
        def __init__(self):
            self.exited = False

        async def __aenter__(self):
            return FakeResp()

        async def __aexit__(self, *args):
            self.exited = True

    cm = FakeStreamCM()

    class FakeClient:
        def stream(self, *args, **kwargs):
            return cm

    monkeypatch.setattr(http_client, "stream", FakeClient().stream)
    with pytest.raises(httpx.ReadError, match="connection reset"):
        await _open_stream(ctx, REQUEST, outbox, http_client)
    assert cm.exited
