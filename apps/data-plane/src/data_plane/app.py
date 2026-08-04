from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import httpx
from cryptography.exceptions import InvalidSignature
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from contract import public_key_from_b64, verify_bundle
from data_plane.adapters import REGISTRY
from data_plane.auth import authenticate, index_keys
from data_plane.cache import read_cached_bundle
from data_plane.canonical import CanonicalRequest, Ctx
from data_plane.config import Config, load_config
from data_plane.holder import BundleHolder
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
    public_key: Ed25519PublicKey | None = None


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
    if bundle is None or state.public_key is None:
        raise RequestRejectedError(503, "bundle_unavailable")

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise RequestRejectedError(401, "missing_bearer_token")
    key = authenticate(auth_header.removeprefix("Bearer "), state.public_key, holder.key_index, holder.revocations)
    if key is None:
        raise RequestRejectedError(401, "invalid_token")

    try:
        req = CanonicalRequest.model_validate(await request.json())
    except (ValueError, ValidationError) as e:
        raise RequestRejectedError(400, "invalid_request") from e
    if req.stream:
        raise RequestRejectedError(501, "streaming_not_implemented")

    decision = evaluate(req, key, bundle, datetime.now(tz=UTC))
    if isinstance(decision, Deny):
        raise RequestRejectedError(decision.status, decision.reason)

    adapter = REGISTRY[decision.provider.kind](decision.provider)
    ctx = Ctx(request_id=uuid4().hex, model=decision.model, provider=decision.provider)
    upstream = adapter.transform_request(req, decision.model)
    try:
        resp = await client.request(upstream.method, upstream.url, headers=upstream.headers, content=upstream.body)
    except httpx.HTTPError as e:
        err = adapter.map_error(e)
        return JSONResponse({"error": {"code": err.code, "message": err.message}}, status_code=err.status)
    if resp.is_error:
        return Response(resp.content, status_code=resp.status_code, media_type="application/json")
    return JSONResponse(adapter.transform_response(resp.content, ctx).model_dump())


async def healthz(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def readyz(_request: Request) -> JSONResponse:
    if holder.current is None:
        return JSONResponse({"status": "no bundle"}, status_code=503)
    return JSONResponse({"status": "ready"})


def _load_cached_bundle(config: Config, public_key: Ed25519PublicKey) -> None:
    try:
        signed = read_cached_bundle(config.cache_dir)
    except ValidationError:
        logger.exception("cached bundle in %s does not parse, ignoring it", config.cache_dir)
        return
    if signed is None:
        logger.warning("no cached bundle in %s, serving 503 until one arrives", config.cache_dir)
        return
    try:
        bundle = verify_bundle(signed, public_key)
    except InvalidSignature:
        logger.exception("cached bundle failed signature verification, ignoring it")
        return
    expired = bundle.expires_at <= datetime.now(tz=UTC)
    if expired and config.staleness_policy == "refuse":
        logger.error("cached bundle expired at %s and policy is refuse, not loading", bundle.expires_at)
        return
    if expired:
        logger.warning("cached bundle expired at %s, serving stale per policy", bundle.expires_at)
    holder.swap(bundle, index_keys(bundle))
    logger.info("loaded bundle %s issued %s", bundle.bundle_id, bundle.issued_at)


@contextlib.asynccontextmanager
async def lifespan(_app: Starlette) -> AsyncIterator[None]:
    config = load_config()
    state.config = config
    state.public_key = public_key_from_b64(config.bundle_public_key_b64)
    _load_cached_bundle(config, state.public_key)
    poller_task = asyncio.create_task(run_poller(config, holder, state.public_key)) if config.control_plane_url else None
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
