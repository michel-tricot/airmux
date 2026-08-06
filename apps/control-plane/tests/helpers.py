from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from typer.testing import CliRunner

if TYPE_CHECKING:
    from fastapi import FastAPI

from contract import private_key_to_b64
from control_plane.app import create_app
from control_plane.config import AuthConfig, BundlePolicy, DatabaseConfig, Settings
from control_plane.db import standalone_transaction
from control_plane.main import app as cli_app
from control_plane.tokens import mint_management_token

PROVIDER = {
    "provider_id": "openai",
    "kind": "openai_compatible",
    "base_url": "https://api.openai.com/v1",
    "credential_ref": "env:OPENAI_API_KEY",
}
MODEL = {"model_id": "gpt-test", "provider_id": "openai", "upstream_model": "gpt-real"}

EMAIL = "michel@example.com"

INIT_TAXONOMY = """
providers:
  - provider_id: openai
    base_url: https://api.openai.com/v1
    credential_ref: env:OPENAI_API_KEY
  - provider_id: anthropic
    kind: anthropic
    base_url: https://api.anthropic.com/v1
    credential_ref: env:ANTHROPIC_API_KEY
models:
  - model_id: gpt-4o
    provider_id: openai
  - model_id: claude-sonnet-4-6
    provider_id: anthropic
"""


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
        async with standalone_transaction(f"sqlite+aiosqlite:///{tmp_path}/cp.db"):
            return await action()

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


def write_config(tmp_path, cp: ControlPlane) -> str:
    """The minimal config file pointing CLI commands at a setup_control_plane database and keys."""
    doc = {
        "control_plane": {
            "database": {"url": f"sqlite+aiosqlite:///{tmp_path}/cp.db"},
            "auth": {"token_signing_key": private_key_to_b64(cp.token_key)},
            "bundle": {"signing_key": private_key_to_b64(cp.bundle_key)},
        }
    }
    cfg = tmp_path / "airllm.yml"
    cfg.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return str(cfg)


def run_init(tmp_path, *extra: str, stdin: str | None = None, taxonomy: str | None = INIT_TAXONOMY):
    """Invoke `airllmcp init` against tmp_path, writing the given taxonomy first (None to write nothing)."""
    if taxonomy is not None:
        (tmp_path / "taxonomy.yml").write_text(taxonomy, encoding="utf-8")
    args = [
        "init",
        *(["--email", EMAIL] if stdin is None else []),
        "--config",
        str(tmp_path / "airllm.yml"),
        "--env-file",
        str(tmp_path / ".env"),
        "--cache-dir",
        str(tmp_path / ".airllm"),
        "--db-url",
        f"sqlite+aiosqlite:///{tmp_path}/cp.db",
        *extra,
    ]
    return CliRunner().invoke(cli_app, args, input=stdin)
