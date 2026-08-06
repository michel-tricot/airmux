from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from control_plane.config import load_settings
from control_plane.db import make_engine, make_session_factory
from control_plane.models import NotOwnedError
from control_plane.routes.instance import router as instance_router
from control_plane.routes.org import router as org_router
from control_plane.routes.sync import router as sync_router

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import Request

    from control_plane.config import Settings


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = app.state.settings
    engine = make_engine(settings.database.url)
    app.state.token_public_key = settings.auth.token_signing_key.public_key()
    app.state.session_factory = make_session_factory(engine)
    try:
        yield
    finally:
        await engine.dispose()


async def not_owned_handler(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="airllm control plane", lifespan=lifespan)
    app.state.settings = settings if settings is not None else load_settings()
    app.add_exception_handler(NotOwnedError, not_owned_handler)
    app.include_router(instance_router)
    app.include_router(org_router)
    app.include_router(sync_router)
    return app
