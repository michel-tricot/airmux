from __future__ import annotations

import asyncio
import contextlib
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

from contract import UsageEventV1, UsageStatus, verify_bundle
from data_plane.adapters import REGISTRY, ProviderAdapter
from data_plane.auth import authenticate
from data_plane.cache import instance_id as cache_instance_id
from data_plane.cache import read_cached_bundle
from data_plane.canonical import CanonicalRequest, CanonicalResponse, Ctx, StreamState, UpstreamRequest, UpstreamStreamError, Usage
from data_plane.config import Config, load_config
from data_plane.heartbeat import run_heartbeat
from data_plane.holder import BundleHolder, BundleSnapshot
from data_plane.ingress import ANTHROPIC, CANONICAL, EgressStream, Ingress
from data_plane.metering import cost_breakdown, estimate_tokens
from data_plane.normalize import normalize_request
from data_plane.outbox import build_outbox
from data_plane.policy import Deny, evaluate
from data_plane.poller import run_poller
from data_plane.transport import client

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from starlette.requests import Request

    from contract import KeyEntry
    from data_plane.outbox import EventOutbox

logger = logging.getLogger("data_plane")

holder = BundleHolder()


@dataclass
class AppState:
    config: Config | None = None
    bundle_public_key: Ed25519PublicKey | None = None
    token_public_key: Ed25519PublicKey | None = None
    outbox: EventOutbox | None = None


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
        return await _handle(request, CANONICAL)
    except RequestRejectedError as e:
        return _error(e.status, e.code)


async def messages(request: Request) -> Response:
    try:
        return await _handle(request, ANTHROPIC)
    except RequestRejectedError as e:
        return _error(e.status, e.code)


async def _authorize(request: Request, ingress: Ingress) -> tuple[CanonicalRequest, KeyEntry, BundleSnapshot]:
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
        req = ingress.parse(await request.body())
    except (ValidationError, ValueError, KeyError) as e:
        raise RequestRejectedError(400, "invalid_request") from e
    return req, key, snap


async def _handle(request: Request, ingress: Ingress) -> Response:
    req, key, snap = await _authorize(request, ingress)
    decision = evaluate(req, key, snap.bundle, datetime.now(tz=UTC))
    if isinstance(decision, Deny):
        _record_denied(key, snap, req)
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
    req = normalize_request(req, decision.model, decision.provider)
    upstream = adapter.transform_request(req, decision.model)
    if req.stream:
        return await _stream(adapter, ctx, upstream, req, ingress)
    try:
        resp = await client.request(upstream.method, upstream.url, headers=upstream.headers, content=upstream.body)
    except httpx.HTTPError as e:
        return _upstream_exception(adapter, ctx, e, req, ingress)
    if resp.is_error:
        return _upstream_error_body(ctx, resp.content, resp.status_code, req, ingress)
    final = adapter.transform_response(resp.content, ctx)
    _record_usage(ctx, final, status="ok", req=req)
    return ingress.render_response(final)


def _status_for_error(e: Exception) -> UsageStatus:
    """Distinguish an upstream timeout from other upstream failures in the usage log."""
    return "timeout" if isinstance(e, httpx.TimeoutException) else "upstream_error"


def _upstream_exception(adapter: ProviderAdapter, ctx: Ctx, e: Exception, req: CanonicalRequest | None, ingress: Ingress) -> Response:
    err = adapter.map_error(e)
    _record_usage(ctx, _empty_response(ctx), status=_status_for_error(e), req=req)
    return ingress.render_error(err)


def _upstream_error_body(ctx: Ctx, body: bytes, status_code: int, req: CanonicalRequest | None, ingress: Ingress) -> Response:
    _record_usage(ctx, _empty_response(ctx), status="upstream_error", req=req)
    return ingress.render_upstream_error(status_code, body)


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


def _record_denied(key: KeyEntry, snap: BundleSnapshot, req: CanonicalRequest) -> None:
    """A policy denial is still metered: attribute it to the caller's key and requested model, with zero usage.

    Only authenticated-but-unauthorized requests are recorded here; raw auth failures have no key to bill.
    """
    if state.outbox is None:
        return
    state.outbox.record(
        UsageEventV1(
            event_id=uuid4(),
            request_id=uuid4().hex,
            occurred_at=datetime.now(tz=UTC),
            org_id=key.org_id,
            key_id=key.key_id,
            model_id=req.model,
            provider_id="",
            bundle_id=snap.bundle.bundle_id,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=0,
            status="denied",
            stream=req.stream,
        )
    )


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
    cost_in, cost_out = cost_breakdown(usage, ctx.model, ctx.provider)
    latency_ms = int((time.monotonic() - ctx.started_at) * 1000)
    if ctx.bundle_id is not None and state.outbox is not None:
        state.outbox.record(
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
                cache_read_tokens=usage.cache_read_tokens,
                cache_write_tokens=usage.cache_write_tokens,
                cost_usd=cost_in + cost_out,
                cost_input_usd=cost_in,
                cost_output_usd=cost_out,
                latency_ms=latency_ms,
                status=status,
                stream=ctx.stream,
            ),
        )
    logger.info(
        "usage request_id=%s model=%s provider=%s status=%s stream=%s input_tokens=%d output_tokens=%d "
        "cache_read=%d cache_write=%d estimated=%s cost_usd=%.6f latency_ms=%d",
        ctx.request_id,
        ctx.model.model_id,
        ctx.provider.provider_id,
        status,
        ctx.stream,
        usage.input_tokens,
        usage.output_tokens,
        usage.cache_read_tokens,
        usage.cache_write_tokens,
        usage.estimated,
        cost_in + cost_out,
        latency_ms,
    )


async def _stream(
    adapter: ProviderAdapter, ctx: Ctx, upstream: UpstreamRequest, req: CanonicalRequest | None = None, ingress: Ingress | None = None
) -> Response:
    """Open the upstream and peek at the status, then hand the socket to the response generator.

    The stack owns the upstream connection: every early return or exception in
    this function closes it, and pop_all transfers that obligation to the
    generator once we commit to streaming.
    """
    ingress = ingress if ingress is not None else CANONICAL
    async with contextlib.AsyncExitStack() as stack:
        try:
            resp = await stack.enter_async_context(client.stream(upstream.method, upstream.url, headers=upstream.headers, content=upstream.body))
            if resp.is_error:
                body = await resp.aread()
                return _upstream_error_body(ctx, body, resp.status_code, req, ingress)
        except httpx.HTTPError as e:
            return _upstream_exception(adapter, ctx, e, req, ingress)
        stream_state = adapter.new_stream_state(ctx)
        handoff = stack.pop_all()

    return StreamingResponse(_events(adapter, ctx, resp, handoff, stream_state, req, ingress.new_egress()), media_type="text/event-stream")


async def _events(  # noqa: PLR0913, PLR0917 the streaming lifecycle genuinely spans these seven
    adapter: ProviderAdapter,
    ctx: Ctx,
    resp: httpx.Response,
    handoff: contextlib.AsyncExitStack,
    stream_state: StreamState,
    req: CanonicalRequest | None,
    egress: EgressStream,
) -> AsyncIterator[bytes]:
    async with handoff:
        try:
            for b in egress.start(ctx):
                yield b
            async for chunk in resp.aiter_bytes():
                for ev in adapter.frame(chunk, stream_state):
                    for c in adapter.transform_stream_event(ev, stream_state):
                        for b in egress.chunk(c):
                            yield b
            final = adapter.finalize(stream_state)
            for b in egress.finish(final):
                yield b
            _record_usage(ctx, final, status="ok", req=req)
        except (UpstreamStreamError, httpx.HTTPError) as e:
            for b in egress.error(adapter.map_error(e)):
                yield b
            _record_usage(ctx, adapter.finalize(stream_state), status=_status_for_error(e), req=req)
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


def create_app(config_override: Config | None = None) -> Starlette:
    """App factory: production loads the config file, tests inject a constructed Config."""

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        config = config_override or load_config()
        if config.dev:
            _configure_dev_logging()
        state.config = config
        state.outbox = build_outbox(config)
        try:
            state.bundle_public_key = config.bundle.public_key
            state.token_public_key = config.auth.token_public_key
            _load_cached_bundle(config, state.bundle_public_key)
            instance_id = cache_instance_id(config.bundle.cache_dir)
            tasks = (
                [
                    asyncio.create_task(run_poller(config, holder, state.bundle_public_key)),
                    asyncio.create_task(state.outbox.run()),
                    asyncio.create_task(run_heartbeat(config, holder, instance_id)),
                ]
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
            state.outbox.close()

    return Starlette(
        routes=[
            Route("/v1/chat/completions", chat_completions, methods=["POST"]),
            Route("/v1/messages", messages, methods=["POST"]),
            Route("/healthz", healthz),
            Route("/readyz", readyz),
        ],
        lifespan=lifespan,
    )


app = create_app()
