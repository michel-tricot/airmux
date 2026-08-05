from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from contract import private_key_from_b64
from control_plane.bootstrap import auto_bootstrap
from control_plane.config import load_settings
from control_plane.db import make_engine, make_session_factory, transaction
from control_plane.models import NotOwnedError
from control_plane.routes.instance import router as instance_router
from control_plane.routes.org import router as org_router
from control_plane.routes.sync import router as sync_router

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import Request


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = load_settings()
    engine = make_engine(settings.database.url)
    app.state.settings = settings
    app.state.token_public_key = private_key_from_b64(settings.auth.token_signing_key).public_key()
    app.state.session_factory = make_session_factory(engine)
    async with transaction(app.state.session_factory):
        await auto_bootstrap(settings)
    try:
        yield
    finally:
        await engine.dispose()


async def not_owned_handler(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


app = FastAPI(title="airllm control plane", lifespan=lifespan)
app.add_exception_handler(NotOwnedError, not_owned_handler)
app.include_router(instance_router)
app.include_router(org_router)
app.include_router(sync_router)
