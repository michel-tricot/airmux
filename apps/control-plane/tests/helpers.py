from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from uuid import UUID

import yaml
from fastapi.routing import APIRoute
from sqlalchemy import event

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncEngine

from pg import TEMPLATE_DB, db_name_for, db_url_for, ensure_database

from contract import MemoryStoreConfig
from control_plane.app import create_app
from control_plane.authority import principal_permissions
from control_plane.authz import ALL_PERMISSIONS, InstanceRole, OrgRole, Permission, Scope
from control_plane.config import DatabaseConfig, Settings
from control_plane.db import standalone_transaction
from control_plane.keys import ManagementKeyGrant, create_management_key
from control_plane.models import Org, OrgMembership, User, set_actor
from control_plane.throttling import ThrottleConfig

PROVIDER = {
    "provider_id": "openai",
    "kind": "openai_compatible",
    "base_url": "https://api.openai.com/v1",
}
MODEL = {
    "model_id": "gpt-test",
    "provider_id": "openai",
    "upstream_model": "gpt-real",
    "input_price_per_mtok": 1.0,
    "output_price_per_mtok": 2.0,
    "cache_read_price_per_mtok": 0.1,
    "cache_write_price_per_mtok": 1.25,
    "input_modalities": ["text"],
    "output_modalities": ["text"],
    "parameter_support": {"temperature": "unsupported"},
}

EMAIL = "michel@example.com"

FIXTURE_ADMIN_EMAIL = "fixture-admin@example.com"


@contextmanager
def captured_sql(app: FastAPI) -> Iterator[list[str]]:
    engine = cast("AsyncEngine", app.state.session_factory.kw["bind"])
    statements: list[str] = []

    def capture(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)


@dataclass(frozen=True)
class ControlPlane:
    app: FastAPI
    db_url: str

    def headers(
        self,
        org_id: UUID | None = None,
        permissions: list[Permission | str] | None = None,
        workspace_id: UUID | None = None,
    ) -> dict[str, str]:

        async def create() -> str:
            async with standalone_transaction(self.db_url):
                admin = await User.first(User.email == FIXTURE_ADMIN_EMAIL)
                if admin is None:
                    admin = User(email=FIXTURE_ADMIN_EMAIL, name="Fixture Admin", instance_role=InstanceRole.owner)
                    await set_actor(admin.id)
                    await admin.save()
                else:
                    await set_actor(admin.id)
                scope = (
                    Scope.workspace(org_id, workspace_id)
                    if workspace_id is not None and org_id is not None
                    else Scope.org(org_id)
                    if org_id
                    else Scope.instance()
                )
                ceiling = frozenset(Permission(permission) for permission in permissions) if permissions is not None else ALL_PERMISSIONS
                _, token = await create_management_key(
                    ManagementKeyGrant(principal_id=admin.id, scope=scope, permissions=ceiling, label="fixture-admin")
                )
                return token

        headers = {"authorization": f"Bearer {asyncio.run(create())}"}
        if org_id is not None:
            headers["X-Test-Org-Id"] = str(org_id)
        return headers

    def headers_for(
        self, org_id: UUID | None, user_id: UUID | str, workspace_id: UUID | None = None, *, permissions: frozenset[Permission] | None = None
    ) -> dict[str, str]:
        """An org key bound to a named user, for the checks an instance owner bypasses."""

        async def create() -> str:
            async with standalone_transaction(self.db_url):
                await set_actor(UUID(str(user_id)))
                principal_id = UUID(str(user_id))
                scope = (
                    Scope.workspace(org_id, workspace_id)
                    if workspace_id is not None and org_id is not None
                    else Scope.org(org_id)
                    if org_id is not None
                    else Scope.instance()
                )
                _, token = await create_management_key(
                    ManagementKeyGrant(
                        principal_id=principal_id,
                        scope=scope,
                        permissions=permissions if permissions is not None else await principal_permissions(principal_id, scope),
                        label="member",
                    )
                )
                return token

        return {"authorization": f"Bearer {asyncio.run(create())}", "X-Test-Org-Id": str(org_id)}


def make_org(client, headers: dict[str, str], name: str = "org-test") -> UUID:
    """Create an org through the API and return its server-minted id."""
    return UUID(client.post("/api/v1/orgs", json={"name": name}, headers=headers).json()["data"]["id"])


def make_workspace(client, headers: dict[str, str], name: str = "ws-test") -> UUID:
    """Create a workspace in the caller's org scope and return its server-minted id; the slug derives from the name."""
    org_id = headers["X-Test-Org-Id"]
    response = client.post(f"/api/v1/orgs/{org_id}/workspaces", json={"name": name}, headers=headers)
    assert response.status_code == 200, response.text
    return UUID(response.json()["data"]["id"])


def run_in_db(tmp_path, action):
    """Run one fat-model call against the test database: tests are non-request code, so they open their own transaction."""

    async def runner():
        async with standalone_transaction(db_url_for(tmp_path)):
            return await action()

    return asyncio.run(runner())


def make_admin(tmp_path, user_id: UUID | str) -> None:

    async def promote():
        user = await User.find_by_id(UUID(str(user_id)))
        assert user is not None
        await set_actor(user.id)
        user.instance_role = InstanceRole.owner
        await user.save()

    run_in_db(tmp_path, promote)


def make_user(tmp_path, email: str, name: str = "") -> User:
    async def create():
        normalized = User.normalize_email(email)
        user = User(email=normalized, name=name or normalized)
        await set_actor(user.id)
        return await user.save()

    return run_in_db(tmp_path, create)


def setup_db(tmp_path) -> str:
    """A bare database for tests that never build the app: a clone of the migrated template.

    An existing database is kept as is.
    """
    return ensure_database(db_name_for(tmp_path), template=TEMPLATE_DB)


def make_app() -> FastAPI:
    """An app with no database behind it, for route-metadata tests; anything that touches the database fails loudly."""
    settings = Settings(
        database=DatabaseConfig(url="postgresql+asyncpg://unused:unused@127.0.0.1:1/unused"),
    )
    return create_app(settings)


def setup_control_plane(tmp_path, secrets=None, *, public_signup: bool = True, throttling: ThrottleConfig | None = None) -> ControlPlane:
    """Database plus a real app over it, for tests that drive the API.

    The secret store is in-process by default so credential writes work and a test can read the
    value back the way a data plane would; pass secrets= to prove a differently configured instance.
    """
    url = setup_db(tmp_path)
    settings = Settings(
        database=DatabaseConfig(url=url),
        secrets=secrets if secrets is not None else MemoryStoreConfig(),
        public_signup=public_signup,
        throttling=throttling if throttling is not None else ThrottleConfig(),
    )
    return ControlPlane(app=create_app(settings), db_url=url)


def write_config(tmp_path, _cp: ControlPlane) -> str:
    """The minimal config file pointing CLI commands at a setup_control_plane database."""
    doc = {"control_plane": {"database": {"url": db_url_for(tmp_path)}}}
    cfg = tmp_path / "airllm.yml"
    cfg.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return str(cfg)


async def seed_admin(email: str = "admin@example.com") -> User:
    user = User(email=email, name=email, instance_role=InstanceRole.owner)
    await set_actor(user.id)
    return await user.save()


async def seed_member(email: str = "member@example.com", org_name: str = "o1") -> tuple[User, UUID]:
    """A plain user with a membership, and the org they belong to."""
    user = User(email=email, name=email)
    await set_actor(user.id)
    await user.save()
    org = await Org.create(org_name)
    await OrgMembership(user_id=user.id, org_id=org.id, role=OrgRole.member).save()
    return user, org.id


def api_routes(app):
    def walk(routes):
        routers = (getattr(route, "original_router", None) for route in routes)
        nested = [route for router in routers if router is not None for route in walk(router.routes)]
        return [*(route for route in routes if isinstance(route, APIRoute)), *nested]

    return walk(app.routes)
