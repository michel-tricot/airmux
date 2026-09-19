from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated, Literal, cast

import anyio
import trio
import typer
import uvicorn
from hypercorn.config import Config
from hypercorn.trio import serve as hypercorn_serve
from starlette.applications import Starlette
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route
from upstream import DEFAULT_USAGE, Reply, buffered, sse

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from hypercorn.typing import ASGIFramework
    from starlette.requests import Request

app = typer.Typer()


def sized_text(size: int, default: str) -> str:
    return default if size == len(default.encode()) else "x" * size


def stream_events(text: str, chunks: int) -> list[bytes]:
    chunk_size = max(1, (len(text) + chunks - 1) // chunks)
    parts = [text[index : index + chunk_size] for index in range(0, len(text), chunk_size)]
    return [
        *[sse({"id": "upstream-response", "choices": [{"index": 0, "delta": {"content": part}, "finish_reason": None}]}) for part in parts],
        sse({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}),
        sse({"choices": [], "usage": DEFAULT_USAGE["openai_compatible"]}),
        b"data: [DONE]\n\n",
    ]


async def complete(request: Request) -> Response:
    if request.scope["http_version"] != request.app.state.http_version:
        return Response("Unexpected benchmark HTTP version", status_code=505)
    body = json.loads(await request.body())
    stream = bool(body.get("stream"))
    expected = {
        "model": "upstream-model-a",
        "messages": [{"role": "user", "content": request.app.state.request_text}],
        "max_tokens": 50,
        **({"stream": True, "stream_options": {"include_usage": True}} if stream else {}),
    }
    if body != expected:
        return Response("Unmatched benchmark payload", status_code=400)
    if request.app.state.delay_ms:
        await anyio.sleep(request.app.state.delay_ms / 1000)
    if not stream:
        return Response(request.app.state.body, media_type="application/json")
    if not request.app.state.stream_chunk_delay_ms:
        return Response(request.app.state.stream_body, media_type="text/event-stream")

    async def events() -> AsyncIterator[bytes]:
        for index, event in enumerate(request.app.state.stream_events):
            if index and request.app.state.stream_chunk_delay_ms:
                await anyio.sleep(request.app.state.stream_chunk_delay_ms / 1000)
            yield event

    return StreamingResponse(events(), media_type="text/event-stream")


async def ready(request: Request) -> Response:
    return Response("ready")


async def serve_http2(upstream: ASGIFramework, config: Config) -> None:
    await hypercorn_serve(upstream, config, mode="asgi")


@app.command()
def serve(  # noqa: PLR0913, PLR0917 CLI flags define the benchmark workload
    port: Annotated[int, typer.Option(min=0, max=65535)],
    delay_ms: Annotated[float, typer.Option(min=0, max=1000)] = 0,
    http_version: Annotated[Literal["http1", "http2"], typer.Option()] = "http1",
    request_bytes: Annotated[int, typer.Option(min=1, max=1_048_576)] = 2,
    response_bytes: Annotated[int, typer.Option(min=1, max=1_048_576)] = 10,
    stream_chunks: Annotated[int, typer.Option(min=1, max=4096)] = 1,
    stream_chunk_delay_ms: Annotated[float, typer.Option(min=0, max=1000)] = 0,
    certfile: Annotated[str | None, typer.Option()] = None,
    keyfile: Annotated[str | None, typer.Option()] = None,
) -> None:
    upstream = Starlette(routes=[Route("/chat/completions", complete, methods=["POST"]), Route("/readyz", ready)])
    upstream.state.delay_ms = delay_ms
    upstream.state.http_version = "2" if http_version == "http2" else "1.1"
    upstream.state.request_text = sized_text(request_bytes, "hi")
    response_text = sized_text(response_bytes, "hello 🌍")
    upstream.state.body = json.dumps(buffered("openai_compatible", Reply(text=response_text))).encode()
    upstream.state.stream_events = stream_events(response_text, stream_chunks)
    upstream.state.stream_body = b"".join(upstream.state.stream_events)
    upstream.state.stream_chunk_delay_ms = stream_chunk_delay_ms
    if http_version == "http1":
        uvicorn.run(upstream, host="127.0.0.1", port=port, log_level="info", access_log=False, timeout_keep_alive=3600)
        return
    if certfile is None or keyfile is None:
        message = "HTTP/2 benchmark providers require --certfile and --keyfile"
        raise typer.BadParameter(message)
    config = Config()
    config.bind = [f"127.0.0.1:{port}"]
    config.certfile = str(certfile)
    config.keyfile = str(keyfile)
    config.alpn_protocols = ["h2"]
    config.keep_alive_timeout = 3600
    config.keep_alive_max_requests = 1_000_000
    trio.run(serve_http2, cast("ASGIFramework", upstream), config)


if __name__ == "__main__":
    app()
