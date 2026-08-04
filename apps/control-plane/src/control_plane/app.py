from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from fastapi import FastAPI

from control_plane.config import load_settings
from control_plane.db import make_engine, make_session_factory
from control_plane.routes.admin import router as admin_router
from control_plane.routes.sync import router as sync_router

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = load_settings()
    engine = make_engine(settings.database.url)
    app.state.settings = settings
    app.state.session_factory = make_session_factory(engine)
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="airllm control plane", lifespan=lifespan)
app.include_router(admin_router)
app.include_router(sync_router)
