"""The request path behind POST /v1/chat/completions, per notes/design/INTERFACE.md.

One pass: authenticate against the bundle, evaluate policy, resolve the credential, reconcile
the request to the target model, translate through the adapter, call the provider, meter, and
answer in the canonical shape with the gateway envelope reporting what was reconciled."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

import httpx
from pydantic import ValidationError
from starlette.responses import JSONResponse, Response

from contract import SecretStoreUnavailableError, UsageEventV1, uuid7
from data_plane.adapters import REGISTRY
from data_plane.adapters.base import Ctx
from data_plane.auth import authenticate
from data_plane.canonical import Adjustment, CanonicalRequest, CanonicalResponse, GatewayInfo, TextPart, Usage
from data_plane.metering import cost_breakdown, estimate_tokens
from data_plane.policy import Allow, Deny, evaluate
from data_plane.runtime import holder, state
from data_plane.transport import client

if TYPE_CHECKING:
    from collections.abc import Sequence

    from starlette.requests import Request

    from contract import CredentialEntry, KeyEntry, ModelEntry, Secret, UsageStatus
    from data_plane.adapters.base import ProviderAdapter
    from data_plane.holder import BundleSnapshot

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


async def complete(request: Request) -> Response:
    try:
        return await _handle(request)
    except RequestRejectedError as e:
        return _error(e.status, e.code, e.message)


async def _authorize(request: Request) -> tuple[CanonicalRequest, KeyEntry, BundleSnapshot]:
    """Authentication and body validation; raises RequestRejectedError on every no."""
    snap = holder.snapshot
    if snap is None:
        raise RequestRejectedError(503, "bundle_unavailable")
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise RequestRejectedError(401, "missing_bearer_token")
    key = authenticate(auth_header.removeprefix("Bearer "), snap.key_index)
    if key is None:
        raise RequestRejectedError(401, "invalid_token")
    try:
        req = CanonicalRequest.model_validate_json(await request.body())
    except ValidationError as e:
        raise RequestRejectedError(400, "invalid_request", str(e.errors(include_url=False)[:3])) from e
    return req, key, snap


def reconcile(req: CanonicalRequest, model: ModelEntry) -> tuple[CanonicalRequest, list[Adjustment]]:
    """What the gateway changes before the adapter runs, every change reported, never silent.

    Extra fields stay on the request but are not rendered by any adapter yet; forwarding the
    compatible ones is profile work, so until then each one is reported as dropped."""
    adjustments = [
        Adjustment(param=param, action="dropped", detail="outside the completion core; forwarding by provider profile has not landed")
        for param in sorted(req.extra)
    ]
    if req.max_tokens and model.max_output_tokens and req.max_tokens > model.max_output_tokens:
        adjustments.append(Adjustment(param="max_tokens", action="clamped", detail=f"model caps output at {model.max_output_tokens} tokens"))
        req = req.model_copy(update={"max_tokens": model.max_output_tokens})
    return req, adjustments


async def _handle(request: Request) -> Response:
    req, key, snap = await _authorize(request)
    decision = evaluate(req, key, snap, datetime.now(tz=UTC))
    if isinstance(decision, Deny):
        _record_denied(key, snap, req)
        raise RequestRejectedError(decision.status, decision.reason)
    if req.stream:
        raise RequestRejectedError(501, "streaming_not_implemented", "the streaming path lands in the next step")

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
    req, adjustments = reconcile(req, decision.model)
    upstream = adapter.transform_request(req, decision.model)
    try:
        resp = await client.request(upstream.method, upstream.url, headers=upstream.headers, content=upstream.body)
    except httpx.HTTPError as e:
        return _upstream_exception(adapter, ctx, e, req)
    if resp.is_error:
        return _upstream_error_body(ctx, resp.content, resp.status_code, req)
    final = adapter.transform_response(resp.content, ctx).model_copy(update={"gateway": GatewayInfo(adjustments=adjustments)})
    _record_usage(ctx, final, status="ok", req=req)
    return JSONResponse(final.model_dump(mode="json", exclude_none=True))


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


def _upstream_exception(adapter: ProviderAdapter, ctx: Ctx, e: Exception, req: CanonicalRequest) -> Response:
    err = adapter.map_error(e)
    _record_usage(ctx, _empty_response(ctx), status=_status_for_error(e), req=req)
    return _error(err.status, err.code, err.message)


def _upstream_error_body(ctx: Ctx, body: bytes, status_code: int, req: CanonicalRequest) -> Response:
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
