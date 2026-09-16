"""Inference request execution and stream accounting."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import anyio
import httpx
from pydantic import ValidationError
from starlette.responses import Response, StreamingResponse

from airmux_runtime.secrets import SecretStoreUnavailableError
from data_plane.canonical import CanonicalAdjustment, CanonicalGatewayInfo, CanonicalRequest, CanonicalResponse, CanonicalUsage
from data_plane.egress import REGISTRY
from data_plane.egress.base import CanonicalError, Ctx, UpstreamProtocolError, UpstreamResponseError, UpstreamStreamError
from data_plane.errors import RequestRejectedError, UnsupportedFeatureError
from data_plane.http import render_rejection
from data_plane.ingress import REGISTRY as INGRESS
from data_plane.ingress import UnknownDialectError, resolve
from data_plane.metering import RequestStart, record_denied, record_usage, status_for_error, status_for_upstream
from data_plane.policy import Allow, Deny
from data_plane.reconcile import reconcile
from data_plane.routing import RoutePlan, plan_routes
from data_plane.runtime import Runtime, runtime_of

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.requests import Request

    from airmux_runtime.secrets import Secret
    from contract import CredentialEntry, KeyEntry, ModelEntry
    from contract.policies import FallbackReason
    from data_plane.bundle.holder import BundleSnapshot
    from data_plane.credentials import CredentialResolver
    from data_plane.egress.base import EgressAdapter, StreamState, UpstreamRequest
    from data_plane.http import InferenceContext
    from data_plane.ingress import IngressAdapter
    from data_plane.ingress.base import ResponseStream
    from data_plane.outbox import EventOutbox


logger = logging.getLogger("data_plane")


async def complete(request: Request, context: InferenceContext) -> Response:
    """Use canonical errors until the caller's dialect is known."""
    body = await _body(request)
    try:
        ingress = resolve(request.headers, body)
    except UnknownDialectError as error:
        raise RequestRejectedError(400, "invalid_dialect", str(error)) from error
    return await _run(IncomingRequest(body=body, context=context, ingress=ingress), runtime_of(request))


async def messages(request: Request, context: InferenceContext) -> Response:
    """The Anthropic-shaped route: the dialect is the route, so every answer speaks it."""
    return await _run(IncomingRequest(body=await _body(request), context=context, ingress=INGRESS["anthropic"]), runtime_of(request))


async def responses(request: Request, context: InferenceContext) -> Response:
    """The Responses route is bound to its dialect so all failures retain its error shape."""
    return await _run(IncomingRequest(body=await _body(request), context=context, ingress=INGRESS["openai_responses"]), runtime_of(request))


async def _body(request: Request) -> dict[str, Any]:
    try:
        body = json.loads(await request.body())
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RequestRejectedError(400, "invalid_request", "the request body must be valid JSON") from error
    if not isinstance(body, dict):
        raise RequestRejectedError(400, "invalid_request", "the request body must be a JSON object")
    return body


@dataclass(frozen=True)
class IncomingRequest:
    body: dict[str, Any]
    context: InferenceContext
    ingress: IngressAdapter


async def _run(incoming: IncomingRequest, runtime: Runtime) -> Response:
    try:
        request, parse_adjustments = _parse(incoming.body, incoming.ingress)
        execution = RequestExecution(
            request=request,
            key=incoming.context.key,
            snapshot=incoming.context.snapshot,
            ingress=incoming.ingress,
            parse_adjustments=tuple(parse_adjustments),
            runtime=runtime,
            start=incoming.context.start,
        )
        return await execution.run()
    except RequestRejectedError as error:
        return render_rejection(incoming.ingress, error)


def _parse(body: dict[str, Any], ingress: IngressAdapter) -> tuple[CanonicalRequest, list[CanonicalAdjustment]]:
    try:
        return ingress.parse(body)
    except ValidationError as error:
        raise RequestRejectedError(400, "invalid_request", str(error.errors(include_url=False)[:3])) from error
    except UnsupportedFeatureError as error:
        raise RequestRejectedError(400, "unsupported_feature", str(error)) from error
    except (TypeError, ValueError) as error:
        raise RequestRejectedError(400, "invalid_request", str(error)) from error


def _transform(adapter: EgressAdapter, request: CanonicalRequest, model: ModelEntry) -> UpstreamRequest:
    try:
        return adapter.transform_request(request, model)
    except ValidationError as error:
        raise RequestRejectedError(400, "invalid_request", str(error.errors(include_url=False)[:3])) from error
    except UnsupportedFeatureError as error:
        raise RequestRejectedError(400, "unsupported_feature", str(error)) from error
    except (TypeError, ValueError) as error:
        raise RequestRejectedError(400, "invalid_request", str(error)) from error


@dataclass(frozen=True)
class StreamSession:
    """Request state shared by opening and folding one provider stream."""

    adapter: EgressAdapter
    ingress: IngressAdapter
    ctx: Ctx
    request: CanonicalRequest
    adjustments: tuple[CanonicalAdjustment, ...]
    outbox: EventOutbox
    http_client: httpx.AsyncClient

    async def open(self, upstream: UpstreamRequest) -> Response:
        async with contextlib.AsyncExitStack() as stack:
            response = await _open_response(stack, self.http_client, upstream)
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
class AttemptFailure:
    response: Response
    reason: FallbackReason | None
    retry_credential: bool


@dataclass(frozen=True)
class RequestExecution:
    """Everything fixed after authentication and parsing for one request."""

    request: CanonicalRequest
    key: KeyEntry
    snapshot: BundleSnapshot
    ingress: IngressAdapter
    parse_adjustments: tuple[CanonicalAdjustment, ...]
    runtime: Runtime
    start: RequestStart

    async def run(self) -> Response:
        if self.snapshot.provider_param_aliases.intersection(self.request.extra):
            raise RequestRejectedError(400, "invalid_request", "Provider parameter aliases must use canonical names")
        plan = plan_routes(self.request, self.key, self.snapshot)
        if isinstance(plan, Deny):
            record_denied(
                self.runtime.outbox,
                self.key,
                self.snapshot.bundle.bundle_id,
                self.request,
                self.start,
            )
            raise RequestRejectedError(plan.status, plan.code, plan.message)
        try:
            async with asyncio.timeout(plan.timeout_ms / 1000 if plan.timeout_ms is not None else None):
                return await self._execute(plan)
        except TimeoutError as error:
            raise RequestRejectedError(504, "fallback_deadline_exceeded", "The fallback time limit was reached") from error

    async def _execute(self, plan: RoutePlan) -> Response:
        attempts = 0
        failure: AttemptFailure | None = None
        for decision in (plan.primary, *plan.backups):
            for entry in self.runtime.credentials.available(decision.candidates):
                if attempts >= plan.max_attempts:
                    break
                credential = await _resolve_credential(entry, self.runtime.credentials)
                if credential is None:
                    continue
                attempts += 1
                outcome = await self._attempt(decision, entry, credential)
                if isinstance(outcome, Response):
                    return outcome
                failure = outcome
                if not failure.retry_credential:
                    break
            if failure is None:
                raise RequestRejectedError(502, "credential_missing")
            if failure.reason not in plan.retry_on or attempts >= plan.max_attempts:
                return failure.response
        if failure is not None:
            return failure.response
        raise RequestRejectedError(502, "credential_missing")

    async def _attempt(self, decision: Allow, entry: CredentialEntry, credential: Secret) -> Response | AttemptFailure:
        egress_kind = decision.model.egress_kind or decision.provider.kind
        routed_request = self.request.model_copy(update={"model": decision.model.model_id})
        request, reconcile_adjustments = reconcile(routed_request, decision.model, decision.profile)
        adjustments = [*self.parse_adjustments, *reconcile_adjustments]
        adapter = REGISTRY[egress_kind](decision.provider, credential)
        ctx = self._ctx(decision, entry)
        upstream = _transform(adapter, request, decision.model)
        try:
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
            response = await self.runtime.http_client.request(upstream.method, upstream.url, headers=upstream.headers, content=upstream.body)
            _check_upstream(response)
            final = adapter.transform_response(response.content, ctx)
        except UpstreamResponseError as error:
            rendered = self._upstream_failure(adapter, ctx, entry, error, request)
            reason: FallbackReason | None = (
                "rate_limited"
                if error.status == httpx.codes.TOO_MANY_REQUESTS
                else "upstream_unavailable"
                if error.status >= httpx.codes.INTERNAL_SERVER_ERROR
                else None
            )
            return AttemptFailure(rendered, reason, error.status in {httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN, httpx.codes.TOO_MANY_REQUESTS})
        except httpx.HTTPError as error:
            rendered = self.ingress.render_error(_record_upstream_error(adapter, ctx, error, request, self.runtime.outbox))
            return AttemptFailure(rendered, "timeout" if isinstance(error, httpx.TimeoutException) else "upstream_unavailable", False)
        except UpstreamProtocolError as error:
            return self.ingress.render_error(_record_upstream_error(adapter, ctx, error, request, self.runtime.outbox))
        except asyncio.CancelledError:
            record_usage(self.runtime.outbox, ctx, _empty_response(ctx), status="cancelled", request=request)
            raise
        final = final.model_copy(update={"gateway": CanonicalGatewayInfo(finish_reason=final.finish_reason, adjustments=adjustments)})
        record_usage(self.runtime.outbox, ctx, final, status="ok", request=request)
        return self.ingress.render_response(final)

    def _ctx(self, decision: Allow, entry: CredentialEntry) -> Ctx:
        return Ctx(
            request_id=self.start.request_id,
            model=decision.model,
            provider=decision.provider,
            stream=self.request.stream,
            org_id=self.key.org_id,
            workspace_id=self.key.workspace_id,
            key_id=self.key.key_id,
            credential_id=entry.ref.secret_id,
            credential_scope=_scope_of(entry),
            bundle_id=self.snapshot.bundle.bundle_id,
            started_at=self.start.started_at,
        )

    def _upstream_failure(
        self,
        adapter: EgressAdapter,
        ctx: Ctx,
        entry: CredentialEntry,
        error: UpstreamResponseError,
        request: CanonicalRequest,
    ) -> Response:
        status = status_for_upstream(error.status)
        if status == "credential_rejected":
            self.runtime.credentials.forget(entry)
        elif status == "rate_limited":
            self.runtime.credentials.rate_limit(entry)
        return self.ingress.render_error(_record_upstream_error(adapter, ctx, error, request, self.runtime.outbox))


def _check_upstream(response: httpx.Response) -> None:
    if response.is_error:
        raise UpstreamResponseError(response.status_code, response.content)


async def _resolve_credential(entry: CredentialEntry, resolver: CredentialResolver) -> Secret | None:
    try:
        secret = await resolver.fetch(entry)
    except SecretStoreUnavailableError as error:
        logger.warning("secret store unavailable for credential %s", entry.ref.secret_id)
        raise RequestRejectedError(503, "credential_backend_unavailable") from error
    return secret


async def _open_response(
    stack: contextlib.AsyncExitStack,
    http_client: httpx.AsyncClient,
    upstream: UpstreamRequest,
) -> httpx.Response:
    response = await stack.enter_async_context(http_client.stream(upstream.method, upstream.url, headers=upstream.headers, content=upstream.body))
    if response.is_error:
        body = await response.aread()
        raise UpstreamResponseError(response.status_code, body)
    return response


def _scope_of(entry: CredentialEntry) -> Literal["platform", "org", "workspace"]:
    if entry.ref.org_id is None:
        return "platform"
    return "workspace" if entry.ref.workspace_id is not None else "org"


def _record_upstream_error(adapter: EgressAdapter, ctx: Ctx, error: Exception, request: CanonicalRequest, outbox: EventOutbox) -> CanonicalError:
    status = status_for_upstream(error.status) if isinstance(error, UpstreamResponseError) else status_for_error(error)
    record_usage(outbox, ctx, _empty_response(ctx), status=status, request=request)
    return adapter.map_error(error)


def _empty_response(ctx: Ctx) -> CanonicalResponse:
    return CanonicalResponse(id=str(ctx.request_id), model=ctx.model.model_id, content=[], finish_reason=None, usage=CanonicalUsage(estimated=True))
