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
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from contract import UsageEventV1, UsageStatus, public_key_from_b64, verify_bundle
from data_plane.adapters import REGISTRY, ProviderAdapter
from data_plane.auth import authenticate
from data_plane.cache import acquire_cache_lock, read_cached_bundle, release_cache_lock
from data_plane.canonical import CanonicalRequest, CanonicalResponse, Ctx, StreamState, UpstreamRequest, UpstreamStreamError, Usage
from data_plane.config import Config, load_config
from data_plane.events import buffer_event, run_flusher
from data_plane.holder import BundleHolder, BundleSnapshot
from data_plane.metering import cost_breakdown, estimate_tokens
from data_plane.policy import Deny, evaluate
from data_plane.poller import run_poller
from data_plane.transport import client

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from starlette.requests import Request

    from contract import KeyEntry

logger = logging.getLogger("data_plane")

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


async def _authorize(request: Request) -> tuple[CanonicalRequest, KeyEntry, BundleSnapshot]:
    """Authentication and body validation; raises RequestRejectedError on every no."""
    snap = holder.snapshot
    if snap is None:
        raise RequestRejectedError(503, "bundle_unavailable")
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise RequestRejectedError(401, "missing_bearer_token")
    if state.token_public_key is None:
        raise RequestRejectedError(503, "token_verifier_unavailable")
    key = authenticate(auth_header.removeprefix("Bearer "), state.token_public_key, snap.key_index, snap.revocations)
    if key is None:
        raise RequestRejectedError(401, "invalid_token")
    try:
        req = CanonicalRequest.model_validate_json(await request.body())
    except ValidationError as e:
        raise RequestRejectedError(400, "invalid_request") from e
    return req, key, snap


async def _handle(request: Request) -> Response:
    req, key, snap = await _authorize(request)
    decision = evaluate(req, key, snap.bundle, datetime.now(tz=UTC))
    if isinstance(decision, Deny):
        raise RequestRejectedError(decision.status, decision.reason)

    adapter = REGISTRY[decision.provider.kind](decision.provider)
    ctx = Ctx(
        request_id=uuid4().hex,
        model=decision.model,
        provider=decision.provider,
        stream=req.stream,
        org_id=key.org_id,
        key_id=key.key_id,
        bundle_id=snap.bundle.bundle_id,
    )
    upstream = adapter.transform_request(req, decision.model)
    if req.stream:
        return await _stream(adapter, ctx, upstream, req)
    try:
        resp = await client.request(upstream.method, upstream.url, headers=upstream.headers, content=upstream.body)
    except httpx.HTTPError as e:
        return _upstream_exception(adapter, ctx, e, req)
    if resp.is_error:
        return _upstream_error_body(ctx, resp.content, resp.status_code, req)
    final = adapter.transform_response(resp.content, ctx)
    _record_usage(ctx, final, status="ok", req=req)
    return Response(final.model_dump_json(), media_type="application/json")


def _upstream_exception(adapter: ProviderAdapter, ctx: Ctx, e: Exception, req: CanonicalRequest | None) -> JSONResponse:
    err = adapter.map_error(e)
    _record_usage(ctx, _empty_response(ctx), status="upstream_error", req=req)
    return JSONResponse({"error": {"code": err.code, "message": err.message}}, status_code=err.status)


def _upstream_error_body(ctx: Ctx, body: bytes, status_code: int, req: CanonicalRequest | None) -> Response:
    _record_usage(ctx, _empty_response(ctx), status="upstream_error", req=req)
    return Response(body, status_code=status_code, media_type="application/json")


def _empty_response(ctx: Ctx) -> CanonicalResponse:
    return CanonicalResponse(id=ctx.request_id, model=ctx.model.model_id, content=[], finish_reason=None, usage=Usage(estimated=True))


def _prompt_text(req: CanonicalRequest) -> str:
    parts: list[str] = []
    for message in req.messages:
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(str(p.get("text", "")) for p in content if isinstance(p, dict))
    return "\n".join(parts)


def _record_usage(ctx: Ctx, final: CanonicalResponse, status: UsageStatus, req: CanonicalRequest | None = None) -> None:
    """The single metering point: estimates fill missing provider counts, then buffer and log."""
    usage = final.usage
    if usage.estimated:
        output_text = "".join(str(part.get("text", "")) for part in final.content if part.get("type") == "text")
        usage = Usage(
            input_tokens=estimate_tokens(_prompt_text(req), ctx.model) if req else 0,
            output_tokens=estimate_tokens(output_text, ctx.model),
            estimated=True,
        )
    cost_in, cost_out = cost_breakdown(usage, ctx.model)
    latency_ms = int((time.monotonic() - ctx.started_at) * 1000)
    if ctx.bundle_id is not None and state.config is not None:
        buffer_event(
            state.config.bundle.cache_dir,
            UsageEventV1(
                event_id=uuid4(),
                request_id=ctx.request_id,
                occurred_at=datetime.now(tz=UTC),
                org_id=ctx.org_id,
                key_id=ctx.key_id,
                model_id=ctx.model.model_id,
                provider_id=ctx.provider.provider_id,
                bundle_id=ctx.bundle_id,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cost_usd=cost_in + cost_out,
                cost_input_usd=cost_in,
                cost_output_usd=cost_out,
                latency_ms=latency_ms,
                status=status,
                stream=ctx.stream,
            ),
        )
    logger.info(
        "usage request_id=%s model=%s provider=%s status=%s stream=%s input_tokens=%d output_tokens=%d estimated=%s cost_usd=%.6f latency_ms=%d",
        ctx.request_id,
        ctx.model.model_id,
        ctx.provider.provider_id,
        status,
        ctx.stream,
        usage.input_tokens,
        usage.output_tokens,
        usage.estimated,
        cost_in + cost_out,
        latency_ms,
    )


def _sse(payload: dict) -> bytes:
    return b"data: " + json.dumps(payload, ensure_ascii=False).encode() + b"\n\n"


async def _stream(adapter: ProviderAdapter, ctx: Ctx, upstream: UpstreamRequest, req: CanonicalRequest | None = None) -> Response:
    """Open the upstream and peek at the status, then hand the socket to the response generator.

    The stack owns the upstream connection: every early return or exception in
    this function closes it, and pop_all transfers that obligation to the
    generator once we commit to streaming.
    """
    async with contextlib.AsyncExitStack() as stack:
        try:
            resp = await stack.enter_async_context(client.stream(upstream.method, upstream.url, headers=upstream.headers, content=upstream.body))
            if resp.is_error:
                body = await resp.aread()
                return _upstream_error_body(ctx, body, resp.status_code, req)
        except httpx.HTTPError as e:
            return _upstream_exception(adapter, ctx, e, req)
        stream_state = adapter.new_stream_state(ctx)
        handoff = stack.pop_all()

    return StreamingResponse(_events(adapter, ctx, resp, handoff, stream_state, req), media_type="text/event-stream")


async def _events(  # noqa: PLR0913, PLR0917 the streaming lifecycle genuinely spans these six
    adapter: ProviderAdapter,
    ctx: Ctx,
    resp: httpx.Response,
    handoff: contextlib.AsyncExitStack,
    stream_state: StreamState,
    req: CanonicalRequest | None,
) -> AsyncIterator[bytes]:
    async with handoff:
        try:
            async for chunk in resp.aiter_bytes():
                for ev in adapter.frame(chunk, stream_state):
                    for c in adapter.transform_stream_event(ev, stream_state):
                        yield b"data: " + c.model_dump_json().encode() + b"\n\n"
            final = adapter.finalize(stream_state)
            yield _sse({"usage": final.usage.model_dump(), "finish_reason": final.finish_reason})
            yield b"data: [DONE]\n\n"
            _record_usage(ctx, final, status="ok", req=req)
        except (UpstreamStreamError, httpx.HTTPError) as e:
            err = adapter.map_error(e)
            yield _sse({"error": {"code": err.code, "message": err.message}})
            _record_usage(ctx, adapter.finalize(stream_state), status="upstream_error", req=req)
        except (asyncio.CancelledError, anyio.get_cancelled_exc_class()):
            _record_usage(ctx, adapter.finalize(stream_state), status="cancelled", req=req)
            raise


async def healthz(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def readyz(_request: Request) -> JSONResponse:
    if holder.snapshot is None:
        return JSONResponse({"status": "no bundle"}, status_code=503)
    return JSONResponse({"status": "ready"})


def _configure_dev_logging() -> None:
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)


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
    holder.admit(bundle, config.bundle.staleness_policy, source="cached")


@contextlib.asynccontextmanager
async def lifespan(_app: Starlette) -> AsyncIterator[None]:
    config = load_config()
    if config.dev:
        _configure_dev_logging()
    state.config = config
    acquire_cache_lock(config.bundle.cache_dir)
    try:
        bundle_key = public_key_from_b64(config.bundle.public_key)
        state.bundle_public_key = bundle_key
        state.token_public_key = public_key_from_b64(config.auth.token_public_key)
        _load_cached_bundle(config, bundle_key)
        tasks = (
            [asyncio.create_task(run_poller(config, holder, bundle_key)), asyncio.create_task(run_flusher(config))]
            if config.control_plane.url
            else []
        )
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
    finally:
        release_cache_lock(config.bundle.cache_dir)


app = Starlette(
    routes=[
        Route("/v1/chat/completions", chat_completions, methods=["POST"]),
        Route("/healthz", healthz),
        Route("/readyz", readyz),
    ],
    lifespan=lifespan,
)
