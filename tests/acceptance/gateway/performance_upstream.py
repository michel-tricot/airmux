from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated

import typer
import uvicorn
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route
from upstream import Reply, buffered, stream_events

if TYPE_CHECKING:
    from starlette.requests import Request

BODY = json.dumps(buffered("openai_compatible", Reply())).encode()
STREAM_BODY = b"".join(stream_events("openai_compatible", Reply()))
app = typer.Typer()


async def complete(request: Request) -> Response:
    body = json.loads(await request.body())
    stream = bool(body.get("stream"))
    return Response(STREAM_BODY if stream else BODY, media_type="text/event-stream" if stream else "application/json")


async def ready(request: Request) -> Response:
    return Response("ready")


@app.command()
def serve(port: Annotated[int, typer.Option(min=1, max=65535)]) -> None:
    upstream = Starlette(routes=[Route("/chat/completions", complete, methods=["POST"]), Route("/readyz", ready)])
    uvicorn.run(upstream, host="127.0.0.1", port=port, log_level="warning", access_log=False)


if __name__ == "__main__":
    app()
