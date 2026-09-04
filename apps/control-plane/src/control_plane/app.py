from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, cast

from fastapi import APIRouter, Depends, FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError, SQLAlchemyError

from control_plane.authority import AuthorizationError, CredentialError
from control_plane.bootstrap import bootstrap_data_plane
from control_plane.config import load_settings
from control_plane.db import make_engine, make_session_factory, transaction
from control_plane.deps import get_session
from control_plane.migrate import head_revision
from control_plane.models import NotOwnedError
from control_plane.openapi import API_DESCRIPTION, API_TAGS, ControlPlaneApp, operation_id
from control_plane.routes.access_keys import router as access_keys_router
from control_plane.routes.auth import router as auth_router
from control_plane.routes.enroll import router as enroll_router
from control_plane.routes.instance import router as instance_router
from control_plane.routes.invitations import router as invitations_router
from control_plane.routes.org import router as org_router
from control_plane.routes.orgs import router as orgs_router
from control_plane.routes.oss import router as oss_router
from control_plane.routes.provider_credentials import instance_router as instance_provider_credentials_router
from control_plane.routes.provider_credentials import router as provider_credentials_router
from control_plane.routes.sync import router as sync_router
from control_plane.routes.taxonomy import router as taxonomy_router
from control_plane.routes.users import router as users_router
from control_plane.routes.workspaces import router as workspaces_router

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import Request
    from sqlalchemy.ext.asyncio import AsyncEngine

    from control_plane.config import Settings


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
        msg = f"database schema is {state} but the code expects {head}: run `airllmcp migrate` (serve --dev migrates automatically)"
        raise RuntimeError(msg)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = app.state.settings
    engine = make_engine(settings.database.url)
    try:
        await _require_migrated_schema(engine)
        app.state.session_factory = make_session_factory(engine)
        if settings.bootstrap is not None:
            async with transaction(app.state.session_factory):
                await bootstrap_data_plane(settings.bootstrap)
        async with settings.secrets.build() as secret_store:
            app.state.secret_store = secret_store
            yield
    finally:
        await engine.dispose()


async def not_owned_handler(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


async def validation_handler(_request: Request, exc: Exception) -> JSONResponse:
    """FastAPI's default handler echoes the offending input back to the caller, which would
    return a provider API key in the response and write it to every access log along the way.

    Dropping `input` and `ctx` leaves the caller everything they need to fix the request, and
    makes the guarantee hold for every body rather than for the ones we remembered to redact."""
    errors = getattr(exc, "errors", list)()
    detail = [{key: value for key, value in error.items() if key not in {"input", "ctx"}} for error in errors]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(detail)})


async def integrity_handler(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": "Request conflicts with existing state"})


async def authorization_handler(_request: Request, exc: Exception) -> JSONResponse:
    error = cast("AuthorizationError", exc)
    return JSONResponse(status_code=403, content={"detail": error.detail})


async def credential_handler(_request: Request, exc: Exception) -> JSONResponse:
    error = cast("CredentialError", exc)
    return JSONResponse(status_code=401, content={"detail": error.detail})


async def healthz(request: Request) -> JSONResponse:
    """Unauthenticated probe for container orchestration; touches the database because process-up alone cannot serve a bundle poll."""
    try:
        async with request.app.state.session_factory() as session:
            await session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse({"status": "ok"})


def create_app(settings: Settings | None = None) -> FastAPI:
    app = ControlPlaneApp(
        title="AirLLM Control Plane API",
        description=API_DESCRIPTION,
        version="0.1.0",
        lifespan=lifespan,
        openapi_tags=API_TAGS,
        generate_unique_id_function=operation_id,
    )
    app.state.settings = settings if settings is not None else load_settings()
    app.add_exception_handler(NotOwnedError, not_owned_handler)
    app.add_exception_handler(RequestValidationError, validation_handler)
    app.add_exception_handler(IntegrityError, integrity_handler)
    app.add_exception_handler(AuthorizationError, authorization_handler)
    app.add_exception_handler(CredentialError, credential_handler)
    app.add_route("/healthz", healthz)
    v1 = APIRouter(prefix="/api/v1", dependencies=[Depends(get_session, scope="function")])
    for router in (
        access_keys_router,
        auth_router,
        enroll_router,
        oss_router,
        instance_router,
        users_router,
        orgs_router,
        invitations_router,
        workspaces_router,
        instance_provider_credentials_router,
        provider_credentials_router,
        org_router,
        sync_router,
        taxonomy_router,
    ):
        v1.include_router(router)
    app.include_router(v1)
    return app
