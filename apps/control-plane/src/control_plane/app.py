from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from control_plane.config import load_settings
from control_plane.db import make_engine, make_session_factory
from control_plane.models import NotOwnedError
from control_plane.routes.auth import router as auth_router
from control_plane.routes.instance import router as instance_router
from control_plane.routes.org import router as org_router
from control_plane.routes.orgs import router as orgs_router
from control_plane.routes.sync import router as sync_router
from control_plane.routes.taxonomy import router as taxonomy_router

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from typing import Any

    from fastapi import Request

    from control_plane.config import Settings

API_TAGS = [
    {"name": "Orgs", "description": "Tenants of the instance; every key, bundle and event belongs to one org"},
    {"name": "Users", "description": "Instance admins, org members and service accounts, with their org memberships"},
    {"name": "Management Tokens", "description": "User-bound bearer tokens for this API, instance- or org-scoped"},
    {"name": "API Keys", "description": "Caller credentials for the gateway: opaque keys whose hashes reach data planes through bundles"},
    {"name": "Auth", "description": "Human login: password and SSO, cookie sessions, account endpoints"},
    {"name": "SSO", "description": "Per-org OIDC issuer connections driving SSO login and home-realm discovery"},
    {"name": "Bundles", "description": "Signed policy bundles compiled per org and polled by data planes"},
    {"name": "Instances", "description": "Data plane instances known to the org through their heartbeats"},
    {"name": "Events", "description": "Usage events reported by data planes"},
    {"name": "Taxonomy", "description": "The models catalog: providers and models compiled into bundles"},
    {"name": "Sync", "description": "Data-plane-facing endpoints: bundle polling, event ingestion, heartbeats"},
]

TAG_GROUPS = [
    {"name": "Instance Admin", "tags": ["Orgs", "Users", "Management Tokens"]},
    {"name": "Org Management", "tags": ["API Keys", "Bundles", "Instances", "Events", "SSO"]},
    {"name": "Account", "tags": ["Auth"]},
    {"name": "Catalog", "tags": ["Taxonomy"]},
    {"name": "Data Plane", "tags": ["Sync"]},
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


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = app.state.settings
    engine = make_engine(settings.database.url)
    app.state.session_factory = make_session_factory(engine)
    try:
        yield
    finally:
        await engine.dispose()


async def not_owned_handler(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


async def healthz(request: Request) -> JSONResponse:
    """Unauthenticated probe for container orchestration; touches the database because process-up alone cannot serve a bundle poll."""
    try:
        async with request.app.state.session_factory() as session:
            await session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse({"status": "ok"})


def create_app(settings: Settings | None = None) -> FastAPI:
    app = ControlPlaneApp(title="airllm control plane", lifespan=lifespan, openapi_tags=API_TAGS)
    app.state.settings = settings if settings is not None else load_settings()
    app.add_exception_handler(NotOwnedError, not_owned_handler)
    app.add_route("/healthz", healthz)
    v1 = APIRouter(prefix="/v1")
    for router in (auth_router, instance_router, orgs_router, org_router, sync_router, taxonomy_router):
        v1.include_router(router)
    app.include_router(v1)
    return app
