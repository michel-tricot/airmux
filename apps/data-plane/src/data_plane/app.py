from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import anyio
import httpx
from cryptography.exceptions import InvalidSignature
from pydantic import ValidationError
from rich.console import Console
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from contract import public_key_from_b64, verify_bundle
from data_plane.adapters import REGISTRY, ProviderAdapter
from data_plane.auth import authenticate, index_keys
from data_plane.cache import read_cached_bundle
from data_plane.canonical import CanonicalRequest, CanonicalResponse, Ctx, UpstreamRequest, UpstreamStreamError
from data_plane.config import Config, load_config
from data_plane.holder import BundleHolder
from data_plane.metering import cost_usd
from data_plane.policy import Deny, evaluate
from data_plane.poller import run_poller
from data_plane.transport import client

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from starlette.requests import Request

logger = logging.getLogger("data_plane")
_console = Console(stderr=True)

holder = BundleHolder()


@dataclass
class AppState:
    config: Config | None = None
    bundle_public_key: Ed25519PublicKey | None = None
    token_public_key: Ed25519PublicKey | None = None


state = AppState()


class RequestRejectedError(Exception):
    def __init__(self, status: int, code: str) -> None:
        self.status = status
        self.code = code
        super().__init__(code)


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code}}, status_code=status)


async def chat_completions(request: Request) -> Response:
    try:
        return await _handle(request)
    except RequestRejectedError as e:
        return _error(e.status, e.code)


async def _handle(request: Request) -> Response:
    bundle = holder.current
    if bundle is None or state.token_public_key is None:
        raise RequestRejectedError(503, "bundle_unavailable")

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise RequestRejectedError(401, "missing_bearer_token")
    key = authenticate(auth_header.removeprefix("Bearer "), state.token_public_key, holder.key_index, holder.revocations)
    if key is None:
        raise RequestRejectedError(401, "invalid_token")

    try:
        req = CanonicalRequest.model_validate(await request.json())
    except (ValueError, ValidationError) as e:
        raise RequestRejectedError(400, "invalid_request") from e

    decision = evaluate(req, key, bundle, datetime.now(tz=UTC))
    if isinstance(decision, Deny):
        raise RequestRejectedError(decision.status, decision.reason)

    adapter = REGISTRY[decision.provider.kind](decision.provider)
    ctx = Ctx(request_id=uuid4().hex, model=decision.model, provider=decision.provider, stream=req.stream)
    upstream = adapter.transform_request(req, decision.model)
    if req.stream:
        return await _stream(adapter, ctx, upstream)
    try:
        resp = await client.request(upstream.method, upstream.url, headers=upstream.headers, content=upstream.body)
    except httpx.HTTPError as e:
        err = adapter.map_error(e)
        return JSONResponse({"error": {"code": err.code, "message": err.message}}, status_code=err.status)
    if resp.is_error:
        return Response(resp.content, status_code=resp.status_code, media_type="application/json")
    final = adapter.transform_response(resp.content, ctx)
    _record_usage(ctx, final, status="ok")
    return JSONResponse(final.model_dump())


STATUS_STYLE = {"ok": "green", "cancelled": "yellow", "upstream_error": "red", "denied": "red", "timeout": "red"}


def _record_usage(ctx: Ctx, final: CanonicalResponse, status: str) -> None:
    """The single metering point; M5 turns this record into a buffered UsageEventV1."""
    cost = cost_usd(final.usage, ctx.model)
    latency_ms = int((time.monotonic() - ctx.started_at) * 1000)
    logger.info(
        "usage request_id=%s model=%s provider=%s status=%s stream=%s input_tokens=%d output_tokens=%d estimated=%s cost_usd=%.6f latency_ms=%d",
        ctx.request_id,
        ctx.model.model_id,
        ctx.provider.provider_id,
        status,
        ctx.stream,
        final.usage.input_tokens,
        final.usage.output_tokens,
        final.usage.estimated,
        cost,
        latency_ms,
    )
    if state.config is not None and state.config.dev:
        tokens = f"{final.usage.input_tokens}→{final.usage.output_tokens} tok" + ("~" if final.usage.estimated else "")
        style = STATUS_STYLE.get(status, "red")
        _console.print(
            f"[dim]{ctx.request_id[:8]}[/dim] [bold]{ctx.model.model_id}[/bold][dim]@{ctx.provider.provider_id}[/dim] "
            f"[{style}]{status:<9}[/{style}] {tokens:<12} ${cost:.6f}  {latency_ms}ms{'  [cyan]stream[/cyan]' if ctx.stream else ''}"
        )


def _sse(payload: dict) -> bytes:
    return b"data: " + json.dumps(payload, ensure_ascii=False).encode() + b"\n\n"


async def _stream(adapter: ProviderAdapter, ctx: Ctx, upstream: UpstreamRequest) -> Response:
    stream_cm = client.stream(upstream.method, upstream.url, headers=upstream.headers, content=upstream.body)
    try:
        resp = await stream_cm.__aenter__()
    except httpx.HTTPError as e:
        err = adapter.map_error(e)
        return JSONResponse({"error": {"code": err.code, "message": err.message}}, status_code=err.status)
    if resp.is_error:
        body = await resp.aread()
        await stream_cm.__aexit__(None, None, None)
        return Response(body, status_code=resp.status_code, media_type="application/json")
    stream_state = adapter.new_stream_state(ctx)

    async def events() -> AsyncIterator[bytes]:
        try:
            async for chunk in resp.aiter_bytes():
                for ev in adapter.frame(chunk, stream_state):
                    for c in adapter.transform_stream_event(ev, stream_state):
                        yield _sse(c.model_dump())
            final = adapter.finalize(stream_state)
            yield _sse({"usage": final.usage.model_dump(), "finish_reason": final.finish_reason})
            yield b"data: [DONE]\n\n"
            _record_usage(ctx, final, status="ok")
        except (UpstreamStreamError, httpx.HTTPError) as e:
            err = adapter.map_error(e)
            yield _sse({"error": {"code": err.code, "message": err.message}})
            _record_usage(ctx, adapter.finalize(stream_state), status="upstream_error")
        except (asyncio.CancelledError, anyio.get_cancelled_exc_class()):
            _record_usage(ctx, adapter.finalize(stream_state), status="cancelled")
            raise
        finally:
            await stream_cm.__aexit__(None, None, None)

    return StreamingResponse(events(), media_type="text/event-stream")


async def healthz(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def readyz(_request: Request) -> JSONResponse:
    if holder.current is None:
        return JSONResponse({"status": "no bundle"}, status_code=503)
    return JSONResponse({"status": "ready"})


def _load_cached_bundle(config: Config, public_key: Ed25519PublicKey) -> None:
    try:
        signed = read_cached_bundle(config.bundle.cache_dir)
    except ValidationError:
        logger.exception("cached bundle in %s does not parse, ignoring it", config.bundle.cache_dir)
        return
    if signed is None:
        logger.warning("no cached bundle in %s, serving 503 until one arrives", config.bundle.cache_dir)
        return
    try:
        bundle = verify_bundle(signed, public_key)
    except InvalidSignature:
        logger.exception("cached bundle failed signature verification, ignoring it")
        return
    expired = bundle.expires_at <= datetime.now(tz=UTC)
    if expired and config.bundle.staleness_policy == "refuse":
        logger.error("cached bundle expired at %s and policy is refuse, not loading", bundle.expires_at)
        return
    if expired:
        logger.warning("cached bundle expired at %s, serving stale per policy", bundle.expires_at)
    holder.swap(bundle, index_keys(bundle))
    logger.info("loaded bundle %s issued %s", bundle.bundle_id, bundle.issued_at)


@contextlib.asynccontextmanager
async def lifespan(_app: Starlette) -> AsyncIterator[None]:
    config = load_config()
    if config.dev and not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    state.config = config
    state.bundle_public_key = public_key_from_b64(config.bundle.public_key)
    state.token_public_key = public_key_from_b64(config.auth.token_public_key)
    _load_cached_bundle(config, state.bundle_public_key)
    poller_task = asyncio.create_task(run_poller(config, holder, state.bundle_public_key)) if config.control_plane.url else None
    try:
        yield
    finally:
        if poller_task is not None:
            poller_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await poller_task


app = Starlette(
    routes=[
        Route("/v1/chat/completions", chat_completions, methods=["POST"]),
        Route("/healthz", healthz),
        Route("/readyz", readyz),
    ],
    lifespan=lifespan,
)
