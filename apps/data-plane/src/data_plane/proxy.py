"""Inference request routing and provider attempts."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Literal

import aiohttp
from pydantic import ValidationError
from pydantic_core import from_json
from starlette.responses import Response

from airmux_runtime.observability import log_event
from airmux_runtime.secrets import SecretStoreUnavailableError
from data_plane.canonical import (
    CanonicalAdjustment,
    CanonicalError,
    CanonicalGatewayInfo,
    CanonicalRequest,
    CanonicalResponse,
    CanonicalUsage,
    GatewayErrorCode,
)
from data_plane.egress import REGISTRY
from data_plane.egress.base import Ctx, UpstreamProtocolError, UpstreamResponseError
from data_plane.errors import RequestRejectedError, UnsupportedFeatureError
from data_plane.http import render_rejection
from data_plane.metering import RequestStart, denied_event, status_for_error, status_for_upstream, usage_event
from data_plane.metrics import upstream_outcome
from data_plane.outbox import OutboxFullError
from data_plane.policy import Allow, Deny
from data_plane.reconcile import reconcile
from data_plane.requirements import requested_capabilities
from data_plane.routing import RoutePlan, plan_routes
from data_plane.runtime import Runtime, runtime_of
from data_plane.streaming import StreamSession

if TYPE_CHECKING:
    from starlette.requests import Request

    from airmux_runtime.secrets import Secret
    from contract import CredentialEntry, KeyEntry, ModelEntry
    from contract.policies import FallbackReason
    from data_plane.bundle.holder import BundleSnapshot
    from data_plane.credentials import CredentialResolver
    from data_plane.egress.base import EgressAdapter, UpstreamRequest
    from data_plane.http import InferenceContext
    from data_plane.ingress import IngressAdapter
    from data_plane.outbox import OutboxReservation
    from data_plane.policies import CompiledRule


logger = logging.getLogger("data_plane")


async def complete(request: Request, context: InferenceContext, ingress: IngressAdapter) -> Response:
    try:
        body = await _body(request)
        runtime = runtime_of(request)
        if body.get("stream") is True:
            route = request.scope["state"]["metrics_route"]
            request.scope["state"]["metrics_stream"] = True
            runtime.metrics.relabel_inflight_stream(route)
        canonical_request, adjustments = _parse(body, ingress)
        execution = RequestExecution(
            request=canonical_request,
            key=context.key,
            snapshot=context.snapshot,
            ingress=ingress,
            parse_adjustments=tuple(adjustments),
            runtime=runtime,
            start=context.start,
        )
        return await execution.run()
    except RequestRejectedError as error:
        return render_rejection(ingress, error)
    except OutboxFullError:
        return render_rejection(ingress, RequestRejectedError(503, GatewayErrorCode.metering_capacity_exhausted))


async def _body(request: Request) -> dict[str, Any]:
    try:
        body = from_json(await request.body())
    except ValueError as error:
        raise RequestRejectedError(400, GatewayErrorCode.invalid_request, "the request body must be valid JSON") from error
    if not isinstance(body, dict):
        raise RequestRejectedError(400, GatewayErrorCode.invalid_request, "the request body must be a JSON object")
    return body


def _parse(body: dict[str, Any], ingress: IngressAdapter) -> tuple[CanonicalRequest, list[CanonicalAdjustment]]:
    try:
        return ingress.parse(body)
    except ValidationError as error:
        raise RequestRejectedError(400, GatewayErrorCode.invalid_request, str(error.errors(include_url=False)[:3])) from error
    except UnsupportedFeatureError as error:
        raise RequestRejectedError(400, GatewayErrorCode.unsupported_feature, str(error)) from error
    except (TypeError, ValueError) as error:
        raise RequestRejectedError(400, GatewayErrorCode.invalid_request, str(error)) from error


def _transform(adapter: EgressAdapter, request: CanonicalRequest, model: ModelEntry) -> UpstreamRequest:
    try:
        return adapter.transform_request(request, model)
    except ValidationError as error:
        raise RequestRejectedError(400, GatewayErrorCode.invalid_request, str(error.errors(include_url=False)[:3])) from error
    except UnsupportedFeatureError as error:
        raise RequestRejectedError(400, GatewayErrorCode.unsupported_feature, str(error)) from error
    except (TypeError, ValueError) as error:
        raise RequestRejectedError(400, GatewayErrorCode.invalid_request, str(error)) from error


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
            raise RequestRejectedError(400, GatewayErrorCode.invalid_request, "Provider parameter aliases must use canonical names")
        plan = plan_routes(self.request, self.key, self.snapshot)
        if isinstance(plan, Deny):
            with self.runtime.outbox.reserve() as reservation:
                reservation.record(denied_event(self.key, self.snapshot.bundle.bundle_id, self.request, self.start))
            raise RequestRejectedError(plan.status, GatewayErrorCode(plan.code), plan.message)
        try:
            if plan.timeout_ms is None:
                return await self._execute(plan)
            async with asyncio.timeout(plan.timeout_ms / 1000):
                return await self._execute(plan)
        except TimeoutError as error:
            raise RequestRejectedError(504, GatewayErrorCode.fallback_deadline_exceeded, "The fallback time limit was reached") from error

    async def _execute(self, plan: RoutePlan) -> Response:
        attempts = 0
        failure: AttemptFailure | None = None
        for decision in (plan.primary, *plan.backups):
            for entry in self.runtime.credentials.available(decision.candidates):
                if attempts >= plan.max_attempts:
                    break
                if plan.budget_rules:
                    self._check_budgets(plan.budget_rules)
                credential = await _resolve_credential(entry, self.runtime.credentials)
                if credential is None:
                    continue
                attempts += 1
                with self.runtime.outbox.reserve() as reservation:
                    outcome = await self._attempt(decision, entry, credential, reservation)
                if isinstance(outcome, Response):
                    return outcome
                failure = outcome
                if not failure.retry_credential:
                    break
            if failure is None:
                raise RequestRejectedError(502, GatewayErrorCode.credential_missing)
            if failure.reason not in plan.retry_on or attempts >= plan.max_attempts:
                return failure.response
        if failure is not None:
            return failure.response
        raise RequestRejectedError(502, GatewayErrorCode.credential_missing)

    def _check_budgets(self, rules: tuple[CompiledRule, ...]) -> None:
        try:
            self.runtime.budgets.check(rules, self.key, datetime.now(UTC))
        except RequestRejectedError:
            with self.runtime.outbox.reserve() as reservation:
                reservation.record(denied_event(self.key, self.snapshot.bundle.bundle_id, self.request, self.start))
            raise

    async def _attempt(
        self,
        decision: Allow,
        entry: CredentialEntry,
        credential: Secret,
        reservation: OutboxReservation,
    ) -> Response | AttemptFailure:
        egress_kind = decision.model.egress_kind or decision.provider.kind
        attempt_started_at = time.monotonic()
        attempt_started_at_utc = datetime.now(UTC)
        routed_request = (
            self.request if self.request.model == decision.model.model_id else self.request.model_copy(update={"model": decision.model.model_id})
        )
        request, reconcile_adjustments = reconcile(
            routed_request,
            decision.model,
            decision.profile,
            decision.policy_max_output_tokens,
        )
        adjustments = [*self.parse_adjustments, *reconcile_adjustments]
        adapter = REGISTRY[egress_kind](decision.provider, credential)
        ctx = self._ctx(decision, entry, attempt_started_at_utc, attempt_started_at)
        upstream = _transform(adapter, request, decision.model)
        try:
            if request.stream:
                session = StreamSession(
                    adapter=adapter,
                    ingress=self.ingress,
                    ctx=ctx,
                    request=request,
                    adjustments=tuple(adjustments),
                    reservation=reservation,
                    http_client=self.runtime.http_client,
                    metrics=self.runtime.metrics,
                    egress_kind=egress_kind,
                    attempt_started_at=attempt_started_at,
                )
                return await session.open(upstream)
            async with self.runtime.provider_http_client.request(
                upstream.method, upstream.url, headers=upstream.headers, data=upstream.body
            ) as response:
                body = await response.read()
                _check_upstream(response.status, body)
            final = adapter.transform_response(body, ctx)
        except UpstreamResponseError as error:
            self.runtime.metrics.observe_upstream(egress_kind, upstream_outcome(error), attempt_started_at)
            status = status_for_upstream(error.status)
            if status == "credential_rejected":
                self.runtime.credentials.forget(entry)
            elif status == "rate_limited":
                self.runtime.credentials.rate_limit(entry)
            rendered = self.ingress.render_error(_record_upstream_error(adapter, ctx, error, request, reservation))
            reason: FallbackReason | None = (
                "rate_limited"
                if error.status == HTTPStatus.TOO_MANY_REQUESTS
                else "upstream_unavailable"
                if error.status >= HTTPStatus.INTERNAL_SERVER_ERROR
                else None
            )
            rejects_credential = error.status in {
                HTTPStatus.UNAUTHORIZED,
                HTTPStatus.FORBIDDEN,
                HTTPStatus.TOO_MANY_REQUESTS,
            }
            return AttemptFailure(rendered, reason, rejects_credential)
        except (aiohttp.ClientError, TimeoutError) as error:
            self.runtime.metrics.observe_upstream(egress_kind, upstream_outcome(error), attempt_started_at)
            rendered = self.ingress.render_error(_record_upstream_error(adapter, ctx, error, request, reservation))
            return AttemptFailure(rendered, "timeout" if isinstance(error, TimeoutError) else "upstream_unavailable", False)
        except UpstreamProtocolError as error:
            self.runtime.metrics.observe_upstream(egress_kind, "protocol_error", attempt_started_at)
            return self.ingress.render_error(_record_upstream_error(adapter, ctx, error, request, reservation))
        except asyncio.CancelledError:
            self.runtime.metrics.observe_upstream(egress_kind, "cancelled", attempt_started_at)
            reservation.record(usage_event(ctx, _empty_response(ctx), status="cancelled", request=request))
            raise
        final = final.model_copy(update={"gateway": CanonicalGatewayInfo(finish_reason=final.finish_reason, adjustments=adjustments)})
        reservation.record(usage_event(ctx, final, status="ok", request=request))
        self.runtime.metrics.observe_upstream(egress_kind, "success", attempt_started_at)
        return self.ingress.render_response(final)

    def _ctx(self, decision: Allow, entry: CredentialEntry, attempt_started_at: datetime, started_at: float) -> Ctx:
        return Ctx(
            request_id=self.start.request_id,
            request_started_at=self.start.request_started_at,
            attempt_started_at=attempt_started_at,
            model=decision.model,
            provider=decision.provider,
            stream=self.request.stream,
            org_id=self.key.org_id,
            workspace_id=self.key.workspace_id,
            key_id=self.key.key_id,
            request_source=self.key.request_source,
            user_id=self.key.user_id,
            requested_model_id=self.request.model,
            requested_capabilities=requested_capabilities(self.request),
            credential_id=entry.ref.secret_id,
            credential_scope=_scope_of(entry),
            bundle_id=self.snapshot.bundle.bundle_id,
            started_at=started_at,
        )


def _check_upstream(status: int, body: bytes) -> None:
    if status >= HTTPStatus.BAD_REQUEST:
        raise UpstreamResponseError(status, body)


async def _resolve_credential(entry: CredentialEntry, resolver: CredentialResolver) -> Secret | None:
    try:
        secret = await resolver.fetch(entry)
    except SecretStoreUnavailableError as error:
        log_event(logger, logging.WARNING, "credential_backend_unavailable", outcome="failed")
        raise RequestRejectedError(503, GatewayErrorCode.credential_backend_unavailable) from error
    return secret


def _scope_of(entry: CredentialEntry) -> Literal["platform", "org", "workspace"]:
    if entry.ref.org_id is None:
        return "platform"
    return "workspace" if entry.ref.workspace_id is not None else "org"


def _record_upstream_error(
    adapter: EgressAdapter,
    ctx: Ctx,
    error: Exception,
    request: CanonicalRequest,
    reservation: OutboxReservation,
) -> CanonicalError:
    status = status_for_upstream(error.status) if isinstance(error, UpstreamResponseError) else status_for_error(error)
    reservation.record(usage_event(ctx, _empty_response(ctx), status=status, request=request))
    return adapter.map_error(error)


def _empty_response(ctx: Ctx) -> CanonicalResponse:
    return CanonicalResponse(id=str(ctx.request_id), model=ctx.model.model_id, content=[], finish_reason=None, usage=CanonicalUsage(estimated=True))
