"""The request path behind POST /v1/chat/completions, per notes/design/INTERFACE.md.

One dialect-blind pass: resolve the caller's ingress adapter, parse to canonical, evaluate
policy, resolve the credential, reconcile to the target model, translate through the egress
adapter, call the provider, meter, and answer in whatever dialect the request spoke."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import TYPE_CHECKING, Any, Literal

import anyio
import httpx
from pydantic import ValidationError
from starlette.responses import Response, StreamingResponse

from contract import SecretStoreUnavailableError, uuid7
from data_plane.auth import authenticate
from data_plane.canonical import Adjustment, CanonicalRequest, CanonicalResponse, GatewayInfo, Usage
from data_plane.egress import REGISTRY
from data_plane.egress.base import CanonicalError, Ctx, UpstreamProtocolError, UpstreamResponseError, UpstreamStreamError
from data_plane.ingress import CANONICAL, resolve
from data_plane.ingress import REGISTRY as INGRESS
from data_plane.metering import record_denied, record_usage, status_for_error, status_for_upstream
from data_plane.policy import Allow, Deny, evaluate
from data_plane.reconcile import reconcile
from data_plane.runtime import Runtime, runtime_of

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from starlette.requests import Request

    from contract import CredentialEntry, KeyEntry, Secret
    from data_plane.bundle.holder import BundleHolder, BundleSnapshot
    from data_plane.credentials import CredentialResolver
    from data_plane.egress.base import EgressAdapter, StreamState, UpstreamRequest
    from data_plane.ingress import IngressAdapter
    from data_plane.ingress.base import ResponseStream
    from data_plane.outbox import EventOutbox


logger = logging.getLogger("data_plane")


class RequestRejectedError(Exception):
    def __init__(self, status: int, code: str, message: str = "") -> None:
        self.status = status
        self.code = code
        self.message = message
        super().__init__(code)


def _rejection(e: RequestRejectedError) -> CanonicalError:
    return CanonicalError(status=e.status, code=e.code, message=e.message)


async def complete(request: Request) -> Response:
    """The native route: the dialect is detected here, at the door, from the parsed body.

    Failures before detection cannot speak a dialect, so they use the canonical envelope,
    which is what the canonical ingress renders anyway."""
    runtime = runtime_of(request)
    try:
        key, snap = _authenticate(request, runtime.holder)
        body = await _body(request)
        ingress = resolve(request.headers, body)
    except RequestRejectedError as e:
        return INGRESS[CANONICAL].render_error(_rejection(e))
    return await _run(body, key, snap, ingress, runtime)


async def messages(request: Request) -> Response:
    """The Anthropic-shaped route: the dialect is the route, so every answer speaks it."""
    ingress = INGRESS["anthropic"]
    runtime = runtime_of(request)
    try:
        key, snap = _authenticate(request, runtime.holder)
        body = await _body(request)
    except RequestRejectedError as e:
        return ingress.render_error(_rejection(e))
    return await _run(body, key, snap, ingress, runtime)


async def _body(request: Request) -> dict[str, Any]:
    try:
        body = json.loads(await request.body())
    except json.JSONDecodeError as e:
        raise RequestRejectedError(400, "invalid_request", str(e)) from e
    if not isinstance(body, dict):
        raise RequestRejectedError(400, "invalid_request", "the request body must be a JSON object")
    return body


async def _run(body: dict[str, Any], key: KeyEntry, snap: BundleSnapshot, ingress: IngressAdapter, runtime: Runtime) -> Response:
    try:
        req, parse_adjustments = _parse(body, ingress)
        return await _serve(req, key, snap, ingress, parse_adjustments=parse_adjustments, runtime=runtime)
    except RequestRejectedError as e:
        return ingress.render_error(_rejection(e))


def _authenticate(request: Request, holder: BundleHolder) -> tuple[KeyEntry, BundleSnapshot]:
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


async def _serve(  # noqa: PLR0913 request serving needs canonical input, auth, bundle, ingress, adjustments, and its app runtime
    req: CanonicalRequest,
    key: KeyEntry,
    snap: BundleSnapshot,
    ingress: IngressAdapter,
    *,
    parse_adjustments: list[Adjustment],
    runtime: Runtime,
) -> Response:
    decision = evaluate(req, key, snap)
    if isinstance(decision, Deny):
        record_denied(runtime.outbox, key, snap.bundle.bundle_id, req)
        raise RequestRejectedError(decision.status, decision.reason)

    entry = decision.candidates[0]
    credential = await _resolve_credential(decision, runtime.credentials)
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
        return await _stream(adapter, ingress, ctx, upstream, req, adjustments, runtime.outbox, runtime.http_client)
    try:
        resp = await runtime.http_client.request(upstream.method, upstream.url, headers=upstream.headers, content=upstream.body)
    except httpx.HTTPError as e:
        return ingress.render_error(_record_upstream_error(adapter, ctx, e, req, runtime.outbox))
    if resp.is_error:
        error = UpstreamResponseError(resp.status_code, resp.content)
        return ingress.render_error(_record_upstream_error(adapter, ctx, error, req, runtime.outbox))
    try:
        final = adapter.transform_response(resp.content, ctx).model_copy(update={"gateway": GatewayInfo(adjustments=adjustments)})
    except UpstreamProtocolError as e:
        return ingress.render_error(_record_upstream_error(adapter, ctx, e, req, runtime.outbox))
    record_usage(runtime.outbox, ctx, final, status="ok", request=req)
    return ingress.render_response(final)


async def _stream(  # noqa: PLR0913, PLR0917 the streaming lifecycle genuinely spans these eight
    adapter: EgressAdapter,
    ingress: IngressAdapter,
    ctx: Ctx,
    upstream: UpstreamRequest,
    req: CanonicalRequest,
    adjustments: Sequence[Adjustment],
    outbox: EventOutbox,
    http_client: httpx.AsyncClient,
) -> Response:
    """Open the upstream and peek at the status, then hand the socket to the response generator.

    The stack owns the upstream connection: every early return or exception in
    this function closes it, and pop_all transfers that obligation to the
    generator once we commit to streaming.
    """
    async with contextlib.AsyncExitStack() as stack:
        try:
            resp = await stack.enter_async_context(http_client.stream(upstream.method, upstream.url, headers=upstream.headers, content=upstream.body))
            if resp.is_error:
                body = await resp.aread()
                error = UpstreamResponseError(resp.status_code, body)
                return ingress.render_error(_record_upstream_error(adapter, ctx, error, req, outbox))
        except httpx.HTTPError as e:
            return ingress.render_error(_record_upstream_error(adapter, ctx, e, req, outbox))
        stream_state = adapter.new_stream_state(ctx)
        handoff = stack.pop_all()

    out = ingress.new_stream()
    return StreamingResponse(_events(adapter, ctx, resp, handoff, stream_state, req, list(adjustments), out, outbox), media_type="text/event-stream")


async def _events(  # noqa: PLR0913, PLR0917 the streaming lifecycle genuinely spans these nine
    adapter: EgressAdapter,
    ctx: Ctx,
    resp: httpx.Response,
    handoff: contextlib.AsyncExitStack,
    stream_state: StreamState,
    req: CanonicalRequest,
    adjustments: list[Adjustment],
    renderer: ResponseStream,
    outbox: EventOutbox,
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
            record_usage(outbox, ctx, final, status="ok", request=req)
        except (UpstreamProtocolError, UpstreamStreamError, httpx.HTTPError) as e:
            for b in renderer.error(adapter.map_error(e)):
                yield b
            record_usage(outbox, ctx, adapter.finalize(stream_state), status=status_for_error(e), request=req)
        except (asyncio.CancelledError, anyio.get_cancelled_exc_class()):
            record_usage(outbox, ctx, adapter.finalize(stream_state), status="cancelled", request=req)
            raise


async def _resolve_credential(decision: Allow, resolver: CredentialResolver) -> Secret:
    """The value behind the first candidate the tier offers.

    Failover across candidates is not here yet, so a broken first key fails the request rather than
    falling through to the second. What it never does is widen to a broader tier: a key that is
    missing or a store that is down must not silently move an org's spend onto the platform account.
    """
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


def _record_upstream_error(adapter: EgressAdapter, ctx: Ctx, error: Exception, req: CanonicalRequest, outbox: EventOutbox) -> CanonicalError:
    status = status_for_upstream(error.status) if isinstance(error, UpstreamResponseError) else status_for_error(error)
    record_usage(outbox, ctx, _empty_response(ctx), status=status, request=req)
    return adapter.map_error(error)


def _empty_response(ctx: Ctx) -> CanonicalResponse:
    return CanonicalResponse(id=ctx.request_id, model=ctx.model.model_id, content=[], finish_reason=None, usage=Usage(estimated=True))
