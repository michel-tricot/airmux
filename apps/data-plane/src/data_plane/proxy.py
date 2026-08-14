"""The request path behind POST /v1/chat/completions, per notes/design/INTERFACE.md.

One dialect-blind pass: resolve the caller's ingress adapter, parse to canonical, evaluate
policy, resolve the credential, reconcile to the target model, translate through the egress
adapter, call the provider, meter, and answer in whatever dialect the request spoke."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

import anyio
import httpx
from pydantic import ValidationError
from starlette.responses import JSONResponse, Response, StreamingResponse

from contract import SecretStoreUnavailableError, UsageEventV1, uuid7
from data_plane.auth import authenticate
from data_plane.canonical import Adjustment, CanonicalRequest, CanonicalResponse, GatewayInfo, TextPart, Usage
from data_plane.egress import REGISTRY
from data_plane.egress.base import CanonicalError, Ctx, UpstreamProtocolError, UpstreamStreamError
from data_plane.ingress import CANONICAL, resolve
from data_plane.ingress import REGISTRY as INGRESS
from data_plane.ingress.canonical import CanonicalResponseStream
from data_plane.metering import cost_breakdown, estimate_tokens
from data_plane.policy import Allow, Deny, evaluate
from data_plane.runtime import holder, state
from data_plane.transport import client

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from starlette.requests import Request

    from contract import CredentialEntry, KeyEntry, ModelEntry, Secret, UsageStatus
    from data_plane.bundle.holder import BundleSnapshot
    from data_plane.egress.base import EgressAdapter, StreamState, UpstreamRequest
    from data_plane.ingress import IngressAdapter
    from data_plane.ingress.base import ResponseStream
    from data_plane.profiles import CompiledProfile


logger = logging.getLogger("data_plane")

REJECTS_CREDENTIAL = frozenset({httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN})


class RequestRejectedError(Exception):
    def __init__(self, status: int, code: str, message: str = "") -> None:
        self.status = status
        self.code = code
        self.message = message
        super().__init__(code)


def _error(status: int, code: str, message: str = "") -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _rejection(e: RequestRejectedError) -> CanonicalError:
    return CanonicalError(status=e.status, code=e.code, message=e.message)


async def complete(request: Request) -> Response:
    """The native route: the dialect is detected here, at the door, from the parsed body.

    Failures before detection cannot speak a dialect, so they use the canonical envelope,
    which is what the canonical ingress renders anyway."""
    try:
        key, snap = _authenticate(request)
        body = await _body(request)
        ingress = resolve(request.headers, body)
    except RequestRejectedError as e:
        return INGRESS[CANONICAL].render_error(_rejection(e))
    return await _run(body, key, snap, ingress)


async def messages(request: Request) -> Response:
    """The Anthropic-shaped route: the dialect is the route, so every answer speaks it."""
    ingress = INGRESS["anthropic"]
    try:
        key, snap = _authenticate(request)
        body = await _body(request)
    except RequestRejectedError as e:
        return ingress.render_error(_rejection(e))
    return await _run(body, key, snap, ingress)


async def _body(request: Request) -> dict[str, Any]:
    try:
        body = json.loads(await request.body())
    except json.JSONDecodeError as e:
        raise RequestRejectedError(400, "invalid_request", str(e)) from e
    if not isinstance(body, dict):
        raise RequestRejectedError(400, "invalid_request", "the request body must be a JSON object")
    return body


async def _run(body: dict[str, Any], key: KeyEntry, snap: BundleSnapshot, ingress: IngressAdapter) -> Response:
    try:
        req, parse_adjustments = _parse(body, ingress)
        return await _serve(req, key, snap, ingress, parse_adjustments)
    except RequestRejectedError as e:
        return ingress.render_error(_rejection(e))


def _authenticate(request: Request) -> tuple[KeyEntry, BundleSnapshot]:
    """The caller against the bundle, before the body is even read; raises RequestRejectedError on every no."""
    snap = holder.snapshot
    if snap is None:
        raise RequestRejectedError(503, "bundle_unavailable")
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise RequestRejectedError(401, "missing_bearer_token")
    key = authenticate(auth_header.removeprefix("Bearer "), snap.key_index)
    if key is None:
        raise RequestRejectedError(401, "invalid_token")
    return key, snap


def _parse(body: dict[str, Any], ingress: IngressAdapter) -> tuple[CanonicalRequest, list[Adjustment]]:
    """The body into canonical, with the dialect's own translation losses carried as adjustments."""
    try:
        return ingress.parse(body)
    except ValidationError as e:
        raise RequestRejectedError(400, "invalid_request", str(e.errors(include_url=False)[:3])) from e
    except ValueError as e:
        raise RequestRejectedError(400, "invalid_request", str(e)) from e


# Params the gateway never forwards, whatever the provider accepts: n asks for a choices axis
# the locked response deliberately does not have, so honoring it would silently discard output.
GATEWAY_HELD = frozenset({"n"})


def _drop_reason(req: CanonicalRequest, profile: CompiledProfile, param: str) -> str | None:
    """Why this extra cannot forward, or None when it can. Lookups against the compiled profile only.

    An extra can never share a core field's name (validation consumes those as the field), so
    the only collision to guard is a provider alias respelling a set core field onto an extra's name."""
    if param in GATEWAY_HELD:
        return "the response carries one completion; a sampling fan-out cannot forward"
    source = profile.respelled.get(param)
    if source is not None and getattr(req, source, None) is not None:
        return f"collides with {source}, which this provider spells {param}"
    if profile.params_closed and param not in profile.accepted:
        return f"{profile.provider_id} accepts only its declared params"
    return None


def reconcile(req: CanonicalRequest, model: ModelEntry, profile: CompiledProfile) -> tuple[CanonicalRequest, list[Adjustment]]:
    """What the gateway changes before the adapter runs, every change reported, never silent.

    Extras the profile allows stay on the request and merge after the typed body at the egress;
    the rest leave here, each with its reason. Absence from a provider's schema is not evidence
    of rejection (19 of 22 leave additionalProperties open), so open schemas forward."""
    adjustments = []
    forwarded: dict[str, object] = {}
    extra = req.extra  # the property copies; read it once
    for param, value in extra.items():
        reason = _drop_reason(req, profile, param)
        if reason is None:
            forwarded[param] = value
        else:
            adjustments.append(Adjustment(param=param, action="dropped", detail=reason))
    if req.max_tokens and model.max_output_tokens and req.max_tokens > model.max_output_tokens:
        adjustments.append(Adjustment(param="max_tokens", action="clamped", detail=f"model caps output at {model.max_output_tokens} tokens"))
        req = req.model_copy(update={"max_tokens": model.max_output_tokens})
    if len(forwarded) == len(extra):
        return req, adjustments
    core = {name: getattr(req, name) for name in CanonicalRequest.model_fields}
    return CanonicalRequest.model_validate({**forwarded, **core}), adjustments


async def _serve(
    req: CanonicalRequest, key: KeyEntry, snap: BundleSnapshot, ingress: IngressAdapter, parse_adjustments: list[Adjustment]
) -> Response:
    decision = evaluate(req, key, snap, datetime.now(tz=UTC))
    if isinstance(decision, Deny):
        _record_denied(key, snap, req)
        raise RequestRejectedError(decision.status, decision.reason)

    entry = decision.candidates[0]
    credential = await _resolve_credential(decision)
    adapter = REGISTRY[decision.provider.kind](decision.provider, credential)
    ctx = Ctx(
        request_id=str(uuid7()),
        model=decision.model,
        provider=decision.provider,
        stream=req.stream,
        org_id=key.org_id,
        workspace_id=key.workspace_id,
        key_id=key.key_id,
        credential_id=entry.ref.secret_id,
        credential_scope=_scope_of(entry),
        bundle_id=snap.bundle.bundle_id,
    )
    req, reconcile_adjustments = reconcile(req, decision.model, decision.profile)
    adjustments = [*parse_adjustments, *reconcile_adjustments]
    upstream = adapter.transform_request(req, decision.model)
    if req.stream:
        return await _stream(adapter, ctx, upstream, req, adjustments, ingress.new_stream())
    try:
        resp = await client.request(upstream.method, upstream.url, headers=upstream.headers, content=upstream.body)
    except httpx.HTTPError as e:
        return _upstream_exception(adapter, ctx, e, req)
    if resp.is_error:
        return _upstream_error_body(ctx, resp.content, resp.status_code, req)
    try:
        final = adapter.transform_response(resp.content, ctx).model_copy(update={"gateway": GatewayInfo(adjustments=adjustments)})
    except UpstreamProtocolError as e:
        return _upstream_exception(adapter, ctx, e, req)
    _record_usage(ctx, final, status="ok", req=req)
    return ingress.render_response(final)


async def _stream(  # noqa: PLR0913, PLR0917 the streaming lifecycle genuinely spans these six
    adapter: EgressAdapter,
    ctx: Ctx,
    upstream: UpstreamRequest,
    req: CanonicalRequest | None = None,
    adjustments: Sequence[Adjustment] = (),
    renderer: ResponseStream | None = None,
) -> Response:
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

    out = renderer if renderer is not None else CanonicalResponseStream()
    return StreamingResponse(_events(adapter, ctx, resp, handoff, stream_state, req, list(adjustments), out), media_type="text/event-stream")


async def _events(  # noqa: PLR0913, PLR0917 the streaming lifecycle genuinely spans these eight
    adapter: EgressAdapter,
    ctx: Ctx,
    resp: httpx.Response,
    handoff: contextlib.AsyncExitStack,
    stream_state: StreamState,
    req: CanonicalRequest | None,
    adjustments: list[Adjustment],
    renderer: ResponseStream,
) -> AsyncIterator[bytes]:
    """One canonical stream, spelled by whichever dialect the caller's ingress picked; an error
    after bytes flowed is a data frame, since the status is already spent."""
    async with handoff:
        try:
            for b in renderer.start(ctx):
                yield b
            async for chunk in resp.aiter_bytes():
                for ev in adapter.frame(chunk, stream_state):
                    for c in adapter.transform_stream_event(ev, stream_state):
                        for b in renderer.chunk(c):
                            yield b
            adapter.validate_stream(stream_state)
            final = adapter.finalize(stream_state)
            for b in renderer.closing(final, adjustments):
                yield b
            _record_usage(ctx, final, status="ok", req=req)
        except (UpstreamProtocolError, UpstreamStreamError, httpx.HTTPError) as e:
            for b in renderer.error(adapter.map_error(e)):
                yield b
            _record_usage(ctx, adapter.finalize(stream_state), status=_status_for_error(e), req=req)
        except (asyncio.CancelledError, anyio.get_cancelled_exc_class()):
            _record_usage(ctx, adapter.finalize(stream_state), status="cancelled", req=req)
            raise


async def _resolve_credential(decision: Allow) -> Secret:
    """The value behind the first candidate the tier offers.

    Failover across candidates is not here yet, so a broken first key fails the request rather than
    falling through to the second. What it never does is widen to a broader tier: a key that is
    missing or a store that is down must not silently move an org's spend onto the platform account.
    """
    resolver = state.credentials
    if resolver is None:
        raise RequestRejectedError(500, "credentials_unavailable")
    entry = decision.candidates[0]
    try:
        secret = await resolver.fetch(entry)
    except SecretStoreUnavailableError as e:
        logger.exception("secret store unavailable for credential %s", entry.ref.secret_id)
        raise RequestRejectedError(503, "credential_backend_unavailable") from e
    if secret is None:
        raise RequestRejectedError(502, "credential_missing")
    return secret


def _scope_of(entry: CredentialEntry) -> Literal["platform", "org", "workspace"]:
    if entry.ref.org_id is None:
        return "platform"
    return "workspace" if entry.ref.workspace_id is not None else "org"


def _status_for_error(e: Exception) -> UsageStatus:
    """Distinguish an upstream timeout from other upstream failures in the usage log."""
    return "timeout" if isinstance(e, httpx.TimeoutException) else "upstream_error"


def _credential_status(status_code: int) -> UsageStatus:
    """A rejected or throttled key is a fact about the credential, which the control plane rolls
    up into its status. Everything else upstream stays undifferentiated."""
    if status_code in REJECTS_CREDENTIAL:
        return "credential_rejected"
    return "rate_limited" if status_code == httpx.codes.TOO_MANY_REQUESTS else "upstream_error"


def _upstream_exception(adapter: EgressAdapter, ctx: Ctx, e: Exception, req: CanonicalRequest | None) -> Response:
    err = adapter.map_error(e)
    _record_usage(ctx, _empty_response(ctx), status=_status_for_error(e), req=req)
    return _error(err.status, err.code, err.message)


def _upstream_error_body(ctx: Ctx, body: bytes, status_code: int, req: CanonicalRequest | None) -> Response:
    """The provider's own error body passes through untouched; the status is what the gateway meters."""
    _record_usage(ctx, _empty_response(ctx), status=_credential_status(status_code), req=req)
    return Response(content=body, status_code=status_code, media_type="application/json")


def _empty_response(ctx: Ctx) -> CanonicalResponse:
    return CanonicalResponse(id=ctx.request_id, model=ctx.model.model_id, content=[], finish_reason=None, usage=Usage(estimated=True))


def _text_of(parts: Sequence[object]) -> str:
    return "\n".join(part.text for part in parts if isinstance(part, TextPart))


def _prompt_text(req: CanonicalRequest) -> str:
    return "\n".join(_text_of(message.content) for message in req.messages)


def _record_denied(key: KeyEntry, snap: BundleSnapshot, req: CanonicalRequest) -> None:
    """A policy denial is still metered: attribute it to the caller's key and requested model, with zero usage.

    Only authenticated-but-unauthorized requests are recorded here; raw auth failures have no key to bill.
    """
    if state.outbox is None:
        return
    state.outbox.record(
        UsageEventV1(
            event_id=uuid7(),
            request_id=uuid7(),
            occurred_at=datetime.now(tz=UTC),
            org_id=key.org_id,
            workspace_id=key.workspace_id,
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
        usage = Usage(
            input_tokens=estimate_tokens(_prompt_text(req), ctx.model) if req else 0,
            output_tokens=estimate_tokens(_text_of(final.content), ctx.model),
            estimated=True,
        )
    cost_in, cost_out = cost_breakdown(usage, ctx.model, ctx.provider)
    latency_ms = int((time.monotonic() - ctx.started_at) * 1000)
    if ctx.bundle_id is not None and state.outbox is not None:
        state.outbox.record(
            UsageEventV1(
                event_id=uuid7(),
                request_id=ctx.request_id,
                occurred_at=datetime.now(tz=UTC),
                org_id=ctx.org_id,
                workspace_id=ctx.workspace_id,
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
                credential_id=ctx.credential_id,
                credential_scope=ctx.credential_scope,
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
