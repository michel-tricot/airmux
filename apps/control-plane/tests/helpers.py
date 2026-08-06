from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

if TYPE_CHECKING:
    from fastapi import FastAPI

from contract import private_key_to_b64
from control_plane.app import create_app
from control_plane.config import AuthConfig, BundlePolicy, DatabaseConfig, Settings
from control_plane.db import make_session_factory, transaction
from control_plane.tokens import mint_management_token

PROVIDER = {
    "provider_id": "openai",
    "kind": "openai_compatible",
    "base_url": "https://api.openai.com/v1",
    "credential_ref": "env:OPENAI_API_KEY",
}
MODEL = {"model_id": "gpt-test", "provider_id": "openai", "upstream_model": "gpt-real"}


@dataclass(frozen=True)
class ControlPlane:
    bundle_key: Ed25519PrivateKey
    token_key: Ed25519PrivateKey
    app: FastAPI

    def headers(self, org_id: str | None = None, token_id: str | None = None) -> dict[str, str]:
        minted = mint_management_token(org_id, self.token_key, datetime.now(tz=UTC), token_id or f"mt-{uuid4().hex[:8]}")
        return {"authorization": f"Bearer {minted}"}


def run_in_db(tmp_path, action):
    """Run one fat-model call against the test database: tests are non-request code, so they open their own transaction."""

    async def runner():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/cp.db")
        async with transaction(make_session_factory(engine)):
            result = await action()
        await engine.dispose()
        return result

    return asyncio.run(runner())


def _create_tables(url: str) -> None:
    async def create() -> None:
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        await engine.dispose()

    asyncio.run(create())


def setup_control_plane(tmp_path) -> ControlPlane:
    url = f"sqlite+aiosqlite:///{tmp_path}/cp.db"
    bundle_key = Ed25519PrivateKey.generate()
    token_key = Ed25519PrivateKey.generate()
    settings = Settings(
        database=DatabaseConfig(url=url),
        auth=AuthConfig(token_signing_key=private_key_to_b64(token_key)),
        bundle=BundlePolicy(signing_key=private_key_to_b64(bundle_key)),
    )
    _create_tables(url)
    return ControlPlane(bundle_key=bundle_key, token_key=token_key, app=create_app(settings))
