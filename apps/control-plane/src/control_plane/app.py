from __future__ import annotations

from fastapi import FastAPI

from control_plane.routes.admin import router as admin_router
from control_plane.routes.sync import router as sync_router

app = FastAPI(title="gateway control plane")
app.include_router(admin_router)
app.include_router(sync_router)
