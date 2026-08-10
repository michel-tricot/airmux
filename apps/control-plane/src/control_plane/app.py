from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from fastapi import APIRouter, FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError, SQLAlchemyError

from control_plane.config import load_settings
from control_plane.db import make_engine, make_session_factory
from control_plane.migrate import head_revision
from control_plane.models import NotOwnedError
from control_plane.routes.auth import router as auth_router
from control_plane.routes.enroll import router as enroll_router
from control_plane.routes.instance import router as instance_router
from control_plane.routes.org import router as org_router
from control_plane.routes.orgs import router as orgs_router
from control_plane.routes.oss import router as oss_router
from control_plane.routes.provider_credentials import router as provider_credentials_router
from control_plane.routes.sync import router as sync_router
from control_plane.routes.taxonomy import router as taxonomy_router
from control_plane.routes.users import router as users_router
from control_plane.routes.workspaces import router as workspaces_router

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from typing import Any

    from fastapi import Request
    from sqlalchemy.ext.asyncio import AsyncEngine

    from control_plane.config import Settings

API_TAGS = [
    {"name": "Orgs", "description": "Tenants of the instance; every key, bundle and event belongs to one org"},
    {"name": "Users", "description": "Instance admins, org members and service accounts, with their org memberships"},
    {
        "name": "Instance Management Keys",
        "x-displayName": "Org Management Keys",
        "description": "Instance-wide oversight of every org's management keys",
    },
    {"name": "Instance Keys", "description": "Admin-held bearer keys for the instance endpoints, and the credential a data plane carries"},
    {"name": "Data Plane", "description": "Data-plane-facing endpoints: bundle polling, event ingestion, heartbeats"},
    {"name": "OSS", "description": "Self-hosted bootstrap: whether this deployment has a claimed account yet, and the quickstart trapdoor"},
    {"name": "Management Keys", "description": "User-bound bearer keys for one org; instance reach is a separate key type"},
    {
        "name": "Org Users",
        "x-displayName": "Users",
        "description": "Membership in the acting org: who belongs to it, and adding or removing them",
    },
    {"name": "Workspaces", "description": "Scopes inside an org where inference keys live; members are drawn from the org"},
    {"name": "Inference Keys", "description": "Caller credentials for the gateway: opaque keys whose hashes reach data planes through bundles"},
    {"name": "Auth", "description": "Human login: password, cookie sessions, account endpoints, CLI device authorization"},
    {"name": "Enrollment", "description": "A user's path into orgs: their standing and their one self-serve personal org"},
    {"name": "Bundles", "description": "Signed policy bundles compiled per org and polled by data planes"},
    {"name": "Events", "description": "Usage events reported by data planes"},
    {"name": "Taxonomy", "description": "The models catalog: providers and models compiled into bundles"},
    {"name": "Provider Credentials", "description": "Provider API keys an org or workspace brings; values live in the secret store, never here"},
    {"name": "Activity", "description": "The audit trail of writes, per org and instance-wide"},
]

TAG_GROUPS = [
    {
        "name": "Org Management",
        "tags": ["Org Users", "Management Keys", "Workspaces", "Inference Keys", "Provider Credentials", "Bundles", "Events", "Activity"],
    },
    {"name": "Account", "tags": ["Auth", "Enrollment"]},
    {"name": "Catalog", "tags": ["Taxonomy"]},
    {"name": "Instance Admin", "tags": ["Orgs", "Users", "Instance Keys", "Instance Management Keys", "Data Plane", "OSS"]},
]


def _api_routes(routes: list[Any]) -> list[APIRoute]:
    """All served routes, reaching through FastAPI's lazily included routers at any depth."""
    routers = (getattr(r, "original_router", None) for r in routes)
    nested = [route for router in routers if router is not None for route in _api_routes(router.routes)]
    return [*(r for r in routes if isinstance(r, APIRoute)), *nested]


class ControlPlaneApp(FastAPI):
    def openapi(self) -> dict[str, Any]:
        """The security arrays are derived from the require() markers on the routes, so the spec
        can never drift from enforcement. OpenAPI 3.1 permits role names in security requirements
        on non-OAuth2 schemes; stamping them here keeps the runtime dependency chain single and
        cached, which Security(scopes=...) would not (its scopes fork the dependency cache key).
        super().openapi() caches and returns the same dict on every call, so the stamping must run
        once: the early return keeps the description append from compounding on each request."""
        if self.openapi_schema:
            return self.openapi_schema
        schema = super().openapi()
        schema["x-tagGroups"] = TAG_GROUPS
        for route in _api_routes(self.routes):
            scopes = [str(s) for dep in route.dependant.dependencies if (s := getattr(dep.call, "required_scope", None)) is not None]
            access = [a for dep in route.dependant.dependencies if (a := getattr(dep.call, "access", None)) is not None]
            for method in route.methods or ():
                operation = schema["paths"]["/v1" + route.path][method.lower()]
                if scopes:
                    operation["security"] = [{"HTTPBearer": scopes}]
                    line = f"Requires the `{'`, `'.join(scopes)}` scope."
                elif "public" in access:
                    operation["security"] = []
                    line = "No authentication required."
                elif "user" in access:
                    line = "Requires an authenticated user; not org-scoped."
                else:
                    continue
                operation["description"] = f"{operation['description']}\n\n{line}" if operation.get("description") else line
        return schema


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


async def healthz(request: Request) -> JSONResponse:
    """Unauthenticated probe for container orchestration; touches the database because process-up alone cannot serve a bundle poll."""
    try:
        async with request.app.state.session_factory() as session:
            await session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse({"status": "ok"})


def _operation_id(route: APIRoute) -> str:
    """The handler name is the operation id, so generated clients read useListOrgs rather than FastAPI's
    useListOrgsV1OrgsGet. Handler names are unique across the routers; test_api_hygiene holds that."""
    return route.name


def create_app(settings: Settings | None = None) -> FastAPI:
    app = ControlPlaneApp(title="airllm control plane", lifespan=lifespan, openapi_tags=API_TAGS, generate_unique_id_function=_operation_id)
    app.state.settings = settings if settings is not None else load_settings()
    app.state.secret_store = app.state.settings.secrets.build()
    app.add_exception_handler(NotOwnedError, not_owned_handler)
    app.add_exception_handler(RequestValidationError, validation_handler)
    app.add_route("/healthz", healthz)
    v1 = APIRouter(prefix="/v1")
    for router in (
        auth_router,
        enroll_router,
        oss_router,
        instance_router,
        users_router,
        orgs_router,
        workspaces_router,
        provider_credentials_router,
        org_router,
        sync_router,
        taxonomy_router,
    ):
        v1.include_router(router)
    app.include_router(v1)
    return app
