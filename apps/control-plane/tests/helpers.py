from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

if TYPE_CHECKING:
    from fastapi import FastAPI

from pg import TEMPLATE_DB, db_name_for, db_url_for, ensure_database

from contract import private_key_to_b64
from control_plane.app import create_app
from control_plane.config import BundlePolicy, DatabaseConfig, Settings
from control_plane.db import standalone_transaction
from control_plane.keys import mint_instance_key, mint_management_key
from control_plane.models import Org, OrgMembership, User, set_actor

PROVIDER = {
    "provider_id": "openai",
    "kind": "openai_compatible",
    "base_url": "https://api.openai.com/v1",
    "credential_ref": "env:OPENAI_API_KEY",
}
MODEL = {"model_id": "gpt-test", "provider_id": "openai", "upstream_model": "gpt-real"}

EMAIL = "michel@example.com"

FIXTURE_ADMIN_EMAIL = "fixture-admin@example.com"


@dataclass(frozen=True)
class ControlPlane:
    bundle_key: Ed25519PrivateKey
    app: FastAPI
    db_url: str

    def headers(self, org_id: UUID | None = None, scopes: list[str] | None = None) -> dict[str, str]:
        """Mint a real backed key for the shared fixture admin: an org key when org_id names one, an instance key otherwise.

        The key type is what carries the scope now, so the two doors a test can knock on are the
        two tables; instance_admin backs both.
        """

        async def mint() -> str:
            async with standalone_transaction(self.db_url):
                admin = await User.first(User.email == FIXTURE_ADMIN_EMAIL)
                if admin is None:
                    admin = User(email=FIXTURE_ADMIN_EMAIL, name="Fixture Admin", instance_admin=True)
                    await set_actor(admin.id)
                    await admin.save()
                else:
                    await set_actor(admin.id)
                if org_id is None:
                    _, token = await mint_instance_key(admin.id, label="fixture-admin", scopes=scopes)
                else:
                    _, token = await mint_management_key(org_id, admin.id, label="fixture-admin", scopes=scopes)
                return token

        return {"authorization": f"Bearer {asyncio.run(mint())}"}


def make_org(client, headers: dict[str, str], name: str = "org-test") -> UUID:
    """Create an org through the API and return its server-minted id."""
    return UUID(client.post("/v1/orgs", json={"name": name}, headers=headers).json()["data"]["id"])


def make_workspace(client, headers: dict[str, str], name: str = "ws-test") -> UUID:
    """Create a workspace in the caller's org scope and return its server-minted id."""
    response = client.post("/v1/org/workspaces", json={"name": name}, headers=headers)
    assert response.status_code == 200, response.text
    return UUID(response.json()["data"]["id"])


def run_in_db(tmp_path, action):
    """Run one fat-model call against the test database: tests are non-request code, so they open their own transaction."""

    async def runner():
        async with standalone_transaction(db_url_for(tmp_path)):
            return await action()

    return asyncio.run(runner())


def make_admin(tmp_path, user_id: UUID | str) -> None:
    """Set the instance_admin bit directly in the database; the API deliberately exposes no path to it."""

    async def promote():
        user = await User.find_by_id(UUID(str(user_id)))
        assert user is not None
        await set_actor(user.id)
        user.instance_admin = True
        await user.save()

    run_in_db(tmp_path, promote)


def setup_db(tmp_path) -> str:
    """A bare database for tests that never build the app: a clone of the migrated template.

    An existing database is kept as is.
    """
    return ensure_database(db_name_for(tmp_path), template=TEMPLATE_DB)


def make_app() -> FastAPI:
    """An app with no database behind it, for route-metadata tests; anything that touches the database fails loudly."""
    settings = Settings(
        database=DatabaseConfig(url="postgresql+asyncpg://unused:unused@127.0.0.1:1/unused"),
        bundle=BundlePolicy(signing_key=private_key_to_b64(Ed25519PrivateKey.generate())),
    )
    return create_app(settings)


def setup_control_plane(tmp_path) -> ControlPlane:
    """Database plus a real app over it, for tests that drive the API."""
    url = setup_db(tmp_path)
    bundle_key = Ed25519PrivateKey.generate()
    settings = Settings(
        database=DatabaseConfig(url=url),
        bundle=BundlePolicy(signing_key=private_key_to_b64(bundle_key)),
    )
    return ControlPlane(bundle_key=bundle_key, app=create_app(settings), db_url=url)


def write_config(tmp_path, cp: ControlPlane) -> str:
    """The minimal config file pointing CLI commands at a setup_control_plane database and keys."""
    doc = {
        "control_plane": {
            "database": {"url": db_url_for(tmp_path)},
            "bundle": {"signing_key": private_key_to_b64(cp.bundle_key)},
        }
    }
    cfg = tmp_path / "airllm.yml"
    cfg.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return str(cfg)


async def seed_admin(email: str = "admin@example.com") -> User:
    """An instance admin straight through the model; the API exposes no path to the bit."""
    user = User(email=email, name=email, instance_admin=True)
    await set_actor(user.id)
    return await user.save()


async def seed_member(email: str = "member@example.com", org_name: str = "o1") -> tuple[User, UUID]:
    """A plain user with a membership, and the org they belong to."""
    user = User(email=email, name=email)
    await set_actor(user.id)
    await user.save()
    org = await Org(name=org_name).save()
    await OrgMembership(user_id=user.id, org_id=org.id).save()
    return user, org.id
