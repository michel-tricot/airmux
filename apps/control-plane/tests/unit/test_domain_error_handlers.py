from __future__ import annotations

from uuid import UUID

import httpx

from control_plane.app import create_app
from control_plane.config import DatabaseConfig, Settings
from control_plane.models.auth_identity import IdentityConflictError
from control_plane.models.org import OrgSlugTakenError
from control_plane.models.org_membership import LastOrgOwnerError
from control_plane.models.policy import InvalidPolicyError
from control_plane.models.user import LastInstanceOwnerError, ManagedServiceAccountInstanceRoleError


async def test_stable_domain_errors_have_central_http_mappings():
    cases = (
        ("invalid-policy", InvalidPolicyError("Invalid policy"), 422, "Invalid policy"),
        ("org-slug-taken", OrgSlugTakenError(), 409, "slug is already taken"),
        ("last-org-owner", LastOrgOwnerError(), 409, "An organization must keep at least one owner"),
        ("last-instance-owner", LastInstanceOwnerError(), 409, "An instance must keep at least one owner"),
        (
            "managed-service-account-instance-role",
            ManagedServiceAccountInstanceRoleError(),
            409,
            "Organization-managed service accounts cannot hold an instance role",
        ),
        ("identity-conflict", IdentityConflictError(), 409, "An account with this email already exists"),
    )
    errors = {name: error for name, error, _, _ in cases}
    app = create_app(Settings(database=DatabaseConfig(url="postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")))

    @app.get("/domain-errors/{name}")
    async def raise_domain_error(name: str) -> None:
        raise errors[name]

    try:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for name, _, status_code, detail in cases:
                response = await client.get(f"/domain-errors/{name}")
                assert response.status_code == status_code
                assert response.json() == {"detail": detail}
    finally:
        app.state.password_workers.close()


async def test_unexpected_errors_keep_the_server_request_id():
    app = create_app(Settings(database=DatabaseConfig(url="postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")))

    @app.get("/unexpected-error")
    async def raise_unexpected_error() -> None:
        message = "private internal detail"
        raise RuntimeError(message)

    try:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/unexpected-error", headers={"x-request-id": "caller-controlled"})
        assert response.status_code == 500
        assert response.json() == {"detail": "Internal Server Error"}
        assert response.headers["x-request-id"] != "caller-controlled"
        assert UUID(response.headers["x-request-id"]).version == 7
    finally:
        app.state.password_workers.close()
