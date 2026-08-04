from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

import anyio
import httpx
from cryptography.exceptions import InvalidSignature
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from contract import UsageEventV1, public_key_from_b64, verify_bundle
from data_plane.adapters import REGISTRY, ProviderAdapter
from data_plane.auth import authenticate, index_keys
from data_plane.cache import acquire_cache_lock, read_cached_bundle, release_cache_lock
from data_plane.canonical import CanonicalRequest, CanonicalResponse, Ctx, UpstreamRequest, UpstreamStreamError, Usage
from data_plane.config import Config, load_config
from data_plane.events import buffer_event, run_flusher
from data_plane.holder import BundleHolder
from data_plane.metering import cost_breakdown, estimate_tokens
from data_plane.policy import Deny, evaluate
from data_plane.poller import run_poller
from data_plane.transport import client

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from starlette.requests import Request

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
    ctx = Ctx(
        request_id=uuid4().hex,
        model=decision.model,
        provider=decision.provider,
        stream=req.stream,
        org_id=key.org_id,
        key_id=key.key_id,
        bundle_id=bundle.bundle_id,
    )
    upstream = adapter.transform_request(req, decision.model)
    prompt = _prompt_text(req)
    if req.stream:
        return await _stream(adapter, ctx, upstream, prompt)
    try:
        resp = await client.request(upstream.method, upstream.url, headers=upstream.headers, content=upstream.body)
    except httpx.HTTPError as e:
        err = adapter.map_error(e)
        _record_usage(ctx, _empty_response(ctx), status="upstream_error", prompt=prompt)
        return JSONResponse({"error": {"code": err.code, "message": err.message}}, status_code=err.status)
    if resp.is_error:
        _record_usage(ctx, _empty_response(ctx), status="upstream_error", prompt=prompt)
        return Response(resp.content, status_code=resp.status_code, media_type="application/json")
    final = adapter.transform_response(resp.content, ctx)
    _record_usage(ctx, final, status="ok", prompt=prompt)
    return JSONResponse(final.model_dump())


def _empty_response(ctx: Ctx) -> CanonicalResponse:
    return CanonicalResponse(id=ctx.request_id, model=ctx.model.model_id, content=[], finish_reason=None, usage=Usage(estimated=True))


STATUS_STYLE = {"ok": "green", "cancelled": "yellow", "upstream_error": "red", "denied": "red", "timeout": "red"}


def _prompt_text(req: CanonicalRequest) -> str:
    parts: list[str] = []
    for message in req.messages:
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(str(p.get("text", "")) for p in content if isinstance(p, dict))
    return "\n".join(parts)


UsageStatus = Literal["ok", "upstream_error", "denied", "timeout", "cancelled"]


def _record_usage(ctx: Ctx, final: CanonicalResponse, status: UsageStatus, prompt: str = "") -> None:
    """The single metering point; M5 turns this record into a buffered UsageEventV1."""
    if final.usage.estimated:
        output_text = "".join(str(part.get("text", "")) for part in final.content if part.get("type") == "text")
        final = final.model_copy(
            update={
                "usage": Usage(
                    input_tokens=estimate_tokens(prompt, ctx.model),
                    output_tokens=estimate_tokens(output_text, ctx.model),
                    estimated=True,
                )
            }
        )
    cost_in, cost_out = cost_breakdown(final.usage, ctx.model)
    cost = cost_in + cost_out
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
                input_tokens=final.usage.input_tokens,
                output_tokens=final.usage.output_tokens,
                cost_usd=cost,
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
        final.usage.input_tokens,
        final.usage.output_tokens,
        final.usage.estimated,
        cost,
        latency_ms,
    )


def _sse(payload: dict) -> bytes:
    return b"data: " + json.dumps(payload, ensure_ascii=False).encode() + b"\n\n"


async def _stream(adapter: ProviderAdapter, ctx: Ctx, upstream: UpstreamRequest, prompt: str = "") -> Response:
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
                _record_usage(ctx, _empty_response(ctx), status="upstream_error", prompt=prompt)
                return Response(body, status_code=resp.status_code, media_type="application/json")
        except httpx.HTTPError as e:
            err = adapter.map_error(e)
            _record_usage(ctx, _empty_response(ctx), status="upstream_error", prompt=prompt)
            return JSONResponse({"error": {"code": err.code, "message": err.message}}, status_code=err.status)
        stream_state = adapter.new_stream_state(ctx)
        handoff = stack.pop_all()

    async def events() -> AsyncIterator[bytes]:
        async with handoff:
            try:
                async for chunk in resp.aiter_bytes():
                    for ev in adapter.frame(chunk, stream_state):
                        for c in adapter.transform_stream_event(ev, stream_state):
                            yield _sse(c.model_dump())
                final = adapter.finalize(stream_state)
                yield _sse({"usage": final.usage.model_dump(), "finish_reason": final.finish_reason})
                yield b"data: [DONE]\n\n"
                _record_usage(ctx, final, status="ok", prompt=prompt)
            except (UpstreamStreamError, httpx.HTTPError) as e:
                err = adapter.map_error(e)
                yield _sse({"error": {"code": err.code, "message": err.message}})
                _record_usage(ctx, adapter.finalize(stream_state), status="upstream_error", prompt=prompt)
            except (asyncio.CancelledError, anyio.get_cancelled_exc_class()):
                _record_usage(ctx, adapter.finalize(stream_state), status="cancelled", prompt=prompt)
                raise

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
    acquire_cache_lock(config.bundle.cache_dir)
    state.bundle_public_key = public_key_from_b64(config.bundle.public_key)
    state.token_public_key = public_key_from_b64(config.auth.token_public_key)
    _load_cached_bundle(config, state.bundle_public_key)
    tasks = (
        [asyncio.create_task(run_poller(config, holder, state.bundle_public_key)), asyncio.create_task(run_flusher(config))]
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
        release_cache_lock(config.bundle.cache_dir)


app = Starlette(
    routes=[
        Route("/v1/chat/completions", chat_completions, methods=["POST"]),
        Route("/healthz", healthz),
        Route("/readyz", readyz),
    ],
    lifespan=lifespan,
)
