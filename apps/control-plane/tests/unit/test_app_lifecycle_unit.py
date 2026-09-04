from __future__ import annotations

from control_plane.app import create_app
from control_plane.config import DatabaseConfig, Settings


def test_management_routes_use_the_api_prefix():
    settings = Settings(
        database=DatabaseConfig(url="postgresql+asyncpg://unused:unused@127.0.0.1/unused"),
    )
    paths = set(create_app(settings).openapi()["paths"])
    assert "/api/v1/auth/me" in paths
    assert not any(path.startswith("/v1/") for path in paths)
