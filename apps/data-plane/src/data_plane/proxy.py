"""The request path behind POST /inf/v1/chat/completions, per notes/design/DATAPLANE.md.

One dialect-blind pass: resolve the caller's ingress adapter, parse to canonical, evaluate
policy, resolve the credential, reconcile to the target model, translate through the egress
adapter, call the provider, meter, and answer in whatever dialect the request spoke."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

import anyio
import httpx
from pydantic import ValidationError
from starlette.responses import Response, StreamingResponse

from contract import PLAYGROUND_COOKIE, SecretStoreUnavailableError, uuid7
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
    from collections.abc import AsyncIterator

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


def _rejection(error: RequestRejectedError) -> CanonicalError:
    return CanonicalError(status=error.status, code=error.code, message=error.message)


async def complete(request: Request) -> Response:
    """The native route: the dialect is detected here, at the door, from the parsed body.

    Failures before detection cannot speak a dialect, so they use the canonical envelope,
    which is what the canonical ingress renders anyway."""
    runtime = runtime_of(request)
    try:
        key, snapshot = _authenticate(request, runtime.holder)
        body = await _body(request)
        ingress = resolve(request.headers, body)
    except RequestRejectedError as error:
        return INGRESS[CANONICAL].render_error(_rejection(error))
    return await _run(body, key, snapshot, ingress, runtime)


async def messages(request: Request) -> Response:
    """The Anthropic-shaped route: the dialect is the route, so every answer speaks it."""
    ingress = INGRESS["anthropic"]
    runtime = runtime_of(request)
    try:
        key, snapshot = _authenticate(request, runtime.holder)
        body = await _body(request)
    except RequestRejectedError as error:
        return ingress.render_error(_rejection(error))
    return await _run(body, key, snapshot, ingress, runtime)


async def responses(request: Request) -> Response:
    """The Responses route is bound to its dialect so all failures retain its error shape."""
    ingress = INGRESS["openai_responses"]
    runtime = runtime_of(request)
    try:
        key, snapshot = _authenticate(request, runtime.holder)
        body = await _body(request)
    except RequestRejectedError as error:
        return ingress.render_error(_rejection(error))
    return await _run(body, key, snapshot, ingress, runtime)


async def _body(request: Request) -> dict[str, Any]:
    try:
        body = json.loads(await request.body())
    except json.JSONDecodeError as error:
        raise RequestRejectedError(400, "invalid_request", str(error)) from error
    if not isinstance(body, dict):
        raise RequestRejectedError(400, "invalid_request", "the request body must be a JSON object")
    return body


async def _run(body: dict[str, Any], key: KeyEntry, snapshot: BundleSnapshot, ingress: IngressAdapter, runtime: Runtime) -> Response:
    try:
        request, parse_adjustments = _parse(body, ingress)
        execution = RequestExecution(
            request=request,
            key=key,
            snapshot=snapshot,
            ingress=ingress,
            parse_adjustments=tuple(parse_adjustments),
            runtime=runtime,
        )
        return await execution.run()
    except RequestRejectedError as error:
        return ingress.render_error(_rejection(error))


def _authenticate(request: Request, holder: BundleHolder) -> tuple[KeyEntry, BundleSnapshot]:
    """The caller against the bundle, before the body is even read; raises RequestRejectedError on every no."""
    bundle_set = holder.current
    if not bundle_set.snapshots:
        raise RequestRejectedError(503, "bundle_unavailable")
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.removeprefix("Bearer ")
    elif request.url.path.endswith("/messages") and request.headers.get("x-api-key"):
        token = request.headers["x-api-key"]
    else:
        token = request.cookies.get(PLAYGROUND_COOKIE, "")
        if not token:
            raise RequestRejectedError(401, "missing_bearer_token")
        if request.headers.get("x-requested-with") is None:
            raise RequestRejectedError(403, "missing_requested_with")
        if request.headers.get("sec-fetch-site") not in (None, "same-origin", "none"):
            raise RequestRejectedError(403, "cross_site_request")
    key = authenticate(token, bundle_set.key_index, datetime.now(tz=UTC))
    if key is None:
        raise RequestRejectedError(401, "invalid_token")
    return key, bundle_set.snapshots[key.org_id]


def _parse(body: dict[str, Any], ingress: IngressAdapter) -> tuple[CanonicalRequest, list[Adjustment]]:
    """The body into canonical, with the dialect's own translation losses carried as adjustments."""
    try:
        return ingress.parse(body)
    except ValidationError as error:
        raise RequestRejectedError(400, "invalid_request", str(error.errors(include_url=False)[:3])) from error
    except (TypeError, ValueError) as error:
        message = str(error)
        code = "unsupported_feature" if message.startswith("unsupported_feature:") else "invalid_request"
        raise RequestRejectedError(400, code, message) from error


@dataclass(frozen=True)
class StreamSession:
    """Request state shared by opening and folding one provider stream."""

    adapter: EgressAdapter
    ingress: IngressAdapter
    ctx: Ctx
    request: CanonicalRequest
    adjustments: tuple[Adjustment, ...]
    outbox: EventOutbox
    http_client: httpx.AsyncClient

    async def open(self, upstream: UpstreamRequest) -> Response:
        async with contextlib.AsyncExitStack() as stack:
            try:
                response = await stack.enter_async_context(
                    self.http_client.stream(upstream.method, upstream.url, headers=upstream.headers, content=upstream.body)
                )
                if response.is_error:
                    body = await response.aread()
                    error = UpstreamResponseError(response.status_code, body)
                    return self.ingress.render_error(_record_upstream_error(self.adapter, self.ctx, error, self.request, self.outbox))
            except httpx.HTTPError as error:
                return self.ingress.render_error(_record_upstream_error(self.adapter, self.ctx, error, self.request, self.outbox))
            stream_state = self.adapter.new_stream_state(self.ctx)
            handoff = stack.pop_all()

        renderer = self.ingress.new_stream()
        return StreamingResponse(self._events(response, handoff, stream_state, renderer), media_type="text/event-stream")

    async def _events(
        self,
        response: httpx.Response,
        handoff: contextlib.AsyncExitStack,
        stream_state: StreamState,
        renderer: ResponseStream,
    ) -> AsyncIterator[bytes]:
        async with handoff:
            try:
                for frame in renderer.start(self.ctx):
                    yield frame
                async for payload in response.aiter_bytes():
                    for event in self.adapter.frame(payload, stream_state):
                        for canonical_chunk in self.adapter.transform_stream_event(event, stream_state):
                            for frame in renderer.chunk(canonical_chunk):
                                yield frame
                self.adapter.validate_stream(stream_state)
                final = self.adapter.finalize(stream_state)
                for frame in renderer.closing(final, list(self.adjustments)):
                    yield frame
                record_usage(self.outbox, self.ctx, final, status="ok", request=self.request)
            except (UpstreamProtocolError, UpstreamStreamError, httpx.HTTPError) as error:
                for frame in renderer.error(self.adapter.map_error(error)):
                    yield frame
                record_usage(
                    self.outbox,
                    self.ctx,
                    self.adapter.finalize(stream_state),
                    status=status_for_error(error),
                    request=self.request,
                )
            except (asyncio.CancelledError, anyio.get_cancelled_exc_class()):
                record_usage(self.outbox, self.ctx, self.adapter.finalize(stream_state), status="cancelled", request=self.request)
                raise


@dataclass(frozen=True)
class RequestExecution:
    """Everything fixed after authentication and parsing for one request."""

    request: CanonicalRequest
    key: KeyEntry
    snapshot: BundleSnapshot
    ingress: IngressAdapter
    parse_adjustments: tuple[Adjustment, ...]
    runtime: Runtime

    async def run(self) -> Response:
        decision = evaluate(self.request, self.key, self.snapshot)
        if isinstance(decision, Deny):
            record_denied(self.runtime.outbox, self.key, self.snapshot.bundle.bundle_id, self.request)
            raise RequestRejectedError(decision.status, decision.reason)

        entry = decision.candidates[0]
        egress_kind = decision.model.egress_kind or decision.provider.kind
        if egress_kind == "openai_responses" and (self.request.stop is not None or self.request.seed is not None):
            raise RequestRejectedError(400, "unsupported_feature", "stop and seed are not representable by Responses")
        if egress_kind != "openai_responses" and (
            self.request.parallel_tool_calls is not None or any(tool.strict is not None for tool in self.request.tools or [])
        ):
            raise RequestRejectedError(400, "unsupported_feature", "the selected egress cannot represent Responses-only request fields")
        credential = await _resolve_credential(decision, self.runtime.credentials)
        adapter = REGISTRY[egress_kind](decision.provider, credential)
        ctx = Ctx(
            request_id=str(uuid7()),
            model=decision.model,
            provider=decision.provider,
            stream=self.request.stream,
            org_id=self.key.org_id,
            workspace_id=self.key.workspace_id,
            key_id=self.key.key_id,
            credential_id=entry.ref.secret_id,
            credential_scope=_scope_of(entry),
            bundle_id=self.snapshot.bundle.bundle_id,
        )
        request, reconcile_adjustments = reconcile(self.request, decision.model, decision.profile)
        adjustments = [*self.parse_adjustments, *reconcile_adjustments]
        try:
            upstream = adapter.transform_request(request, decision.model)
        except ValueError as error:
            message = str(error)
            code = "unsupported_feature" if message.startswith("unsupported_feature:") else "invalid_request"
            raise RequestRejectedError(400, code, message) from error
        if request.stream:
            session = StreamSession(
                adapter=adapter,
                ingress=self.ingress,
                ctx=ctx,
                request=request,
                adjustments=tuple(adjustments),
                outbox=self.runtime.outbox,
                http_client=self.runtime.http_client,
            )
            return await session.open(upstream)
        try:
            response = await self.runtime.http_client.request(upstream.method, upstream.url, headers=upstream.headers, content=upstream.body)
        except httpx.HTTPError as error:
            return self.ingress.render_error(_record_upstream_error(adapter, ctx, error, request, self.runtime.outbox))
        if response.is_error:
            error = UpstreamResponseError(response.status_code, response.content)
            return self.ingress.render_error(_record_upstream_error(adapter, ctx, error, request, self.runtime.outbox))
        try:
            final = adapter.transform_response(response.content, ctx).model_copy(update={"gateway": GatewayInfo(adjustments=adjustments)})
        except UpstreamProtocolError as error:
            return self.ingress.render_error(_record_upstream_error(adapter, ctx, error, request, self.runtime.outbox))
        record_usage(self.runtime.outbox, ctx, final, status="ok", request=request)
        return self.ingress.render_response(final)


async def _resolve_credential(decision: Allow, resolver: CredentialResolver) -> Secret:
    """The value behind the first candidate the tier offers.

    Failover across candidates is not here yet, so a broken first key fails the request rather than
    falling through to the second. What it never does is widen to a broader tier: a key that is
    missing or a store that is down must not silently move an org's spend onto the platform account.
    """
    entry = decision.candidates[0]
    try:
        secret = await resolver.fetch(entry)
    except SecretStoreUnavailableError as error:
        logger.exception("secret store unavailable for credential %s", entry.ref.secret_id)
        raise RequestRejectedError(503, "credential_backend_unavailable") from error
    if secret is None:
        raise RequestRejectedError(502, "credential_missing")
    return secret


def _scope_of(entry: CredentialEntry) -> Literal["platform", "org", "workspace"]:
    if entry.ref.org_id is None:
        return "platform"
    return "workspace" if entry.ref.workspace_id is not None else "org"


def _record_upstream_error(adapter: EgressAdapter, ctx: Ctx, error: Exception, request: CanonicalRequest, outbox: EventOutbox) -> CanonicalError:
    status = status_for_upstream(error.status) if isinstance(error, UpstreamResponseError) else status_for_error(error)
    record_usage(outbox, ctx, _empty_response(ctx), status=status, request=request)
    return adapter.map_error(error)


def _empty_response(ctx: Ctx) -> CanonicalResponse:
    return CanonicalResponse(id=ctx.request_id, model=ctx.model.model_id, content=[], finish_reason=None, usage=Usage(estimated=True))
