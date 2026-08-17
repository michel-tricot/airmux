from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import httpx
import pytest
import respx
from conftest import CTX, ORG, TEXT_LOG, WORKSPACE, make_adapter, make_outbox, mock_control_plane, sse
from starlette.responses import Response, StreamingResponse
from starlette.testclient import TestClient

from contract import uuid7
from data_plane.canonical import CanonicalRequest
from data_plane.egress.base import Ctx, UpstreamRequest
from data_plane.ingress import CANONICAL
from data_plane.ingress import REGISTRY as INGRESS
from data_plane.proxy import StreamSession

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Iterator

    from data_plane.outbox import SqliteOutbox

UPSTREAM = UpstreamRequest(method="POST", url="https://api.openai.com/v1/chat/completions", headers={}, body=b"{}")
REQUEST = CanonicalRequest(model="gpt-test", messages=[{"role": "user", "content": "hi"}], stream=True)


@pytest.fixture
def metering(tmp_path, http_client) -> Iterator[tuple[Ctx, SqliteOutbox]]:
    outbox = make_outbox(tmp_path, http_client)
    ctx = replace(
        CTX,
        request_id=str(uuid7()),
        org_id=ORG,
        workspace_id=WORKSPACE,
        key_id="k-dev",
        credential_id=uuid7(),
        credential_scope="workspace",
        bundle_id=uuid7(),
    )
    yield ctx, outbox
    outbox.close()


def _event(outbox: SqliteOutbox):
    (event,) = outbox.next_batch(10)
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
    text = "".join(e["delta"]["text"] for e in events if e.get("delta", {}).get("type") == "text")
    assert text == "héllo \U0001f30d world"
    assert events[-1]["usage"] == {"input_tokens": 5, "output_tokens": 7, "cache_read_tokens": 0, "cache_write_tokens": 0, "estimated": False}
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
    session = StreamSession(
        adapter=make_adapter(),
        ingress=INGRESS[CANONICAL],
        ctx=ctx,
        request=request,
        adjustments=(),
        outbox=outbox,
        http_client=http_client,
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
    event = _event(outbox)
    assert event.status == "cancelled"
    assert event.input_tokens > 0
    assert event.output_tokens > 0
    assert event.cost_usd > 0


@respx.mock
async def test_mid_stream_error_event_becomes_sse_error(metering, http_client):
    ctx, outbox = metering
    hi = {"id": "cmpl-9", "model": "gpt-real", "choices": [{"index": 0, "delta": {"content": "héllo "}, "finish_reason": None}]}
    log = sse(hi) + sse({"error": {"code": "overloaded", "message": "try later"}})
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, content=log))
    chunks = [chunk async for chunk in _body_gen(await _open_stream(ctx, REQUEST, outbox, http_client))]
    assert any(b'"code": "overloaded"' in c for c in chunks)
    assert _event(outbox).status == "upstream_error"


@respx.mock
async def test_stream_ending_before_the_provider_terminal_becomes_sse_error(metering, http_client):
    ctx, outbox = metering
    incomplete = TEXT_LOG.removesuffix(b"data: [DONE]\n\n")
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, content=incomplete))
    chunks = [chunk async for chunk in _body_gen(await _open_stream(ctx, REQUEST, outbox, http_client))]
    assert any(b'"code": "invalid_upstream_response"' in chunk for chunk in chunks)
    assert _event(outbox).status == "upstream_error"


@respx.mock
async def test_malformed_stream_event_becomes_sse_error(metering, http_client):
    ctx, outbox = metering
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, content=b"data: not-json\n\n"))
    chunks = [chunk async for chunk in _body_gen(await _open_stream(ctx, REQUEST, outbox, http_client))]
    assert any(b'"code": "invalid_upstream_response"' in chunk for chunk in chunks)
    assert _event(outbox).status == "upstream_error"


async def test_error_body_read_failure_closes_upstream_and_maps(monkeypatch, metering, http_client):
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
    response = await _open_stream(ctx, REQUEST, outbox, http_client)
    assert cm.exited
    assert response.status_code == 502
    assert _event(outbox).status == "upstream_error"
