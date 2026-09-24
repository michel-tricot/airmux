from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, cast

from fastapi import APIRouter, Depends, FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError, SQLAlchemyError
from starlette.routing import Route

from airmux_runtime.observability import configure_logger, flush_logger
from control_plane.authority import AuthorizationError, CredentialError
from control_plane.bootstrap import bootstrap_data_plane
from control_plane.config import load_settings
from control_plane.db import make_engine, make_session_factory, transaction
from control_plane.deps import get_session
from control_plane.http import ObservabilityMiddleware, api_routes, route_paths
from control_plane.metrics import ControlPlaneMetrics, metrics_endpoint
from control_plane.migrate import head_revision
from control_plane.models import NotOwnedError
from control_plane.models.auth_identity import IdentityConflictError
from control_plane.models.common import InvalidCursorError
from control_plane.models.org import OrgSlugTakenError
from control_plane.models.org_membership import LastOrgOwnerError
from control_plane.models.policy import InvalidPolicyError
from control_plane.models.user import LastInstanceOwnerError, ManagedServiceAccountInstanceRoleError
from control_plane.openapi import API_DESCRIPTION, API_TAGS, ControlPlaneApp, operation_id
from control_plane.passwords import PasswordWorkers
from control_plane.publisher import run_publisher
from control_plane.routes.auth import router as auth_router
from control_plane.routes.enroll import router as enroll_router
from control_plane.routes.instance import router as instance_router
from control_plane.routes.invitations import router as invitations_router
from control_plane.routes.management_keys import router as management_keys_router
from control_plane.routes.org import router as org_router
from control_plane.routes.orgs import router as orgs_router
from control_plane.routes.oss import router as oss_router
from control_plane.routes.policies import router as policies_router
from control_plane.routes.provider_credentials import instance_router as instance_provider_credentials_router
from control_plane.routes.provider_credentials import router as provider_credentials_router
from control_plane.routes.reports import router as reports_router
from control_plane.routes.sync import router as sync_router
from control_plane.routes.taxonomy import router as taxonomy_router
from control_plane.routes.users import router as users_router
from control_plane.routes.workspaces import router as workspaces_router
from control_plane.taxonomy import UnknownProviderError
from control_plane.throttling import LocalThrottleBackend, ThrottleBackend, ThrottledError, ThrottleMiddleware, compile_routes, denied_response

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import Request
    from sqlalchemy.ext.asyncio import AsyncEngine

    from control_plane.config import Settings

logger = logging.getLogger("control_plane")


async def _require_migrated_schema(engine: AsyncEngine) -> None:
    """Refuse to serve a database that is empty or behind: one clear startup error beats one 500 per request."""
    try:
        async with engine.connect() as conn:
            current = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one_or_none()
    except ProgrammingError:
        current = None
    head = head_revision()
    if current != head:
        state = f"at revision {current}" if current else "empty"
        msg = f"database schema is {state} but the code expects {head}: run `airmux control-plane migrate`"
        raise RuntimeError(msg)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = app.state.settings
    configure_logger(logger, dev=settings.dev)
    engine = make_engine(settings.database.url)
    async with contextlib.AsyncExitStack() as cleanup:
        cleanup.callback(flush_logger, logger)
        cleanup.push_async_callback(asyncio.to_thread, app.state.metrics.shutdown)
        cleanup.push_async_callback(engine.dispose)
        cleanup.callback(app.state.password_workers.close)
        await _require_migrated_schema(engine)
        app.state.session_factory = make_session_factory(engine)
        if settings.bootstrap is not None:
            async with transaction(app.state.session_factory):
                await bootstrap_data_plane(settings.bootstrap)
        async with settings.secrets.build() as secret_store:
            app.state.secret_store = secret_store
            publisher = asyncio.create_task(run_publisher(app.state.session_factory, app.state.metrics), name="bundle-publisher")
            try:
                yield
            finally:
                publisher.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await publisher


async def not_owned_handler(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


async def validation_handler(_request: Request, exc: Exception) -> JSONResponse:
    """FastAPI's default handler echoes the offending input back to the caller, which would
    return a provider API key in the response and write it to every access log along the way.

    Dropping `input` and `ctx` leaves the caller everything they need to fix the request, and
    makes the guarantee hold for every body rather than for the ones we remembered to redact."""
    errors = getattr(exc, "errors", list)()
    if any(error.get("loc") == ("query", "cursor") for error in errors):
        return JSONResponse(status_code=422, content={"detail": "invalid cursor"})
    detail = [{key: value for key, value in error.items() if key not in {"input", "ctx"}} for error in errors]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(detail)})


async def integrity_handler(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": "Request conflicts with existing state"})


async def domain_validation_handler(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


async def domain_conflict_handler(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


async def org_slug_taken_handler(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": "slug is already taken"})


async def identity_conflict_handler(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": "An account with this email already exists"})


async def unknown_provider_handler(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


async def authorization_handler(_request: Request, exc: Exception) -> JSONResponse:
    error = cast("AuthorizationError", exc)
    return JSONResponse(status_code=403, content={"detail": error.detail})


async def credential_handler(_request: Request, exc: Exception) -> JSONResponse:
    error = cast("CredentialError", exc)
    return JSONResponse(status_code=401, content={"detail": error.detail})


async def healthz(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def readyz(request: Request) -> JSONResponse:
    try:
        async with request.app.state.session_factory() as session:
            await session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse({"status": "ready"})


async def throttled_handler(_request: Request, exc: Exception) -> JSONResponse:
    return denied_response(cast("ThrottledError", exc).decision)


async def unexpected_handler(request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"},
        headers={"x-request-id": str(request.state.request_id)},
    )


def create_app(settings: Settings | None = None, *, throttle_backend: ThrottleBackend | None = None) -> FastAPI:
    metrics = ControlPlaneMetrics()
    app = ControlPlaneApp(
        title="airmux Control Plane API",
        description=API_DESCRIPTION,
        version="0.1.0",
        lifespan=lifespan,
        openapi_tags=API_TAGS,
        generate_unique_id_function=operation_id,
    )
    app.state.settings = settings if settings is not None else load_settings()
    app.state.metrics = metrics
    throttling = app.state.settings.throttling
    app.state.throttle_backend = throttle_backend if throttle_backend is not None else LocalThrottleBackend(max_buckets=throttling.max_buckets)
    app.state.password_workers = PasswordWorkers(workers=throttling.password_workers, queue=throttling.password_queue)
    app.add_exception_handler(ThrottledError, throttled_handler)
    app.add_exception_handler(NotOwnedError, not_owned_handler)
    app.add_exception_handler(InvalidCursorError, domain_validation_handler)
    app.add_exception_handler(RequestValidationError, validation_handler)
    app.add_exception_handler(IntegrityError, integrity_handler)
    app.add_exception_handler(AuthorizationError, authorization_handler)
    app.add_exception_handler(CredentialError, credential_handler)
    app.add_exception_handler(InvalidPolicyError, domain_validation_handler)
    app.add_exception_handler(OrgSlugTakenError, org_slug_taken_handler)
    app.add_exception_handler(LastOrgOwnerError, domain_conflict_handler)
    app.add_exception_handler(LastInstanceOwnerError, domain_conflict_handler)
    app.add_exception_handler(ManagedServiceAccountInstanceRoleError, domain_conflict_handler)
    app.add_exception_handler(IdentityConflictError, identity_conflict_handler)
    app.add_exception_handler(UnknownProviderError, unknown_provider_handler)
    app.add_exception_handler(Exception, unexpected_handler)
    admin = APIRouter(routes=[Route("/healthz", healthz), Route("/readyz", readyz), Route("/metrics", metrics_endpoint)])
    v1 = APIRouter(prefix="/api/v1", dependencies=[Depends(get_session, scope="function")])
    routers = (
        management_keys_router,
        auth_router,
        enroll_router,
        oss_router,
        instance_router,
        users_router,
        orgs_router,
        invitations_router,
        workspaces_router,
        policies_router,
        instance_provider_credentials_router,
        provider_credentials_router,
        org_router,
        reports_router,
        sync_router,
        taxonomy_router,
    )
    for router in routers:
        v1.include_router(router)
    app.include_router(admin)
    app.include_router(v1)
    routes = api_routes(routers)
    app.add_middleware(ThrottleMiddleware, backend=app.state.throttle_backend, config=throttling, routes=compile_routes(routes), metrics=metrics)
    metric_routes = (*route_paths((admin,)), *route_paths(routers, prefix="/api/v1"))
    app.add_middleware(ObservabilityMiddleware, metrics=metrics, routes=metric_routes)
    return app
