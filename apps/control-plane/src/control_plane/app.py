from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from control_plane.config import load_settings
from control_plane.db import make_engine, make_session_factory
from control_plane.models import NotOwnedError
from control_plane.routes.instance import router as instance_router
from control_plane.routes.org import router as org_router
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
    {"name": "API Keys", "description": "Caller credentials for the gateway: signed JWTs distributed to data planes through bundles"},
    {"name": "Bundles", "description": "Signed policy bundles compiled per org and polled by data planes"},
    {"name": "Instances", "description": "Data plane instances known to the org through their heartbeats"},
    {"name": "Events", "description": "Usage events reported by data planes"},
    {"name": "Taxonomy", "description": "The models catalog: providers and models compiled into bundles"},
    {"name": "Sync", "description": "Data-plane-facing endpoints: bundle polling, event ingestion, heartbeats"},
]

TAG_GROUPS = [
    {"name": "Instance Admin", "tags": ["Orgs", "Users", "Management Tokens"]},
    {"name": "Org Management", "tags": ["API Keys", "Bundles", "Instances", "Events"]},
    {"name": "Catalog", "tags": ["Taxonomy"]},
    {"name": "Data Plane", "tags": ["Sync"]},
]


class ControlPlaneApp(FastAPI):
    def openapi(self) -> dict[str, Any]:
        schema = super().openapi()
        schema["x-tagGroups"] = TAG_GROUPS
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
    for router in (instance_router, org_router, sync_router, taxonomy_router):
        v1.include_router(router)
    app.include_router(v1)
    return app
