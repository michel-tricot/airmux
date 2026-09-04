from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4

import httpx
import pytest
import respx

from contract import (
    INFERENCE_TOKEN_PREFIX,
    BundleV1,
    Catalog,
    CredentialEntry,
    KeyEntry,
    ModelEntry,
    ProviderEntry,
    Secret,
    SecretPurpose,
    SecretRef,
    token_hash,
    uuid7,
)
from data_plane.app import create_app
from data_plane.bundle import RemoteBundleConfig
from data_plane.cache import CachedBundles, write_cached_bundles
from data_plane.config import Config, DevNullOutboxConfig, SqliteOutboxConfig
from data_plane.control_plane_link import ControlPlaneLink
from data_plane.egress import REGISTRY
from data_plane.egress.base import Ctx
from data_plane.outbox import SqliteOutbox

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.applications import Starlette

NOW = datetime.now(tz=UTC)
ORG = uuid7()
WORKSPACE = uuid7()

CONTROL_PLANE_URL = "http://cp.test"

PROVIDER = ProviderEntry(provider_id="p1", kind="openai_compatible", base_url="https://api.openai.com/v1")
MODEL = ModelEntry(
    model_id="gpt-test",
    provider_id="p1",
    upstream_model="gpt-real",
    input_price_per_mtok=1.0,
    output_price_per_mtok=2.0,
    cache_read_price_per_mtok=0.1,
    cache_write_price_per_mtok=1.25,
    context_window=128000,
    max_output_tokens=4096,
    input_modalities=["text", "image", "pdf"],
    output_modalities=["text"],
    capabilities=["streaming", "tools", "reasoning", "structured_output"],
)


def make_credential(service="p1", name="default", org=ORG, **scope) -> CredentialEntry:
    """A credential entry naming a secret.

    scope takes workspace, priority, version and secret_id. Passing secret_id describes the same
    credential twice, which is what a rotation looks like from the data plane.
    """
    secret_id = scope.get("secret_id") or uuid7()
    workspace = scope.get("workspace")
    ref = SecretRef(purpose=SecretPurpose.provider, service=service, name=name, secret_id=secret_id, org_id=org, workspace_id=workspace)
    return CredentialEntry(ref=ref, priority=scope.get("priority", 100), version=scope.get("version", 1))


def make_key(key_id: UUID | str = "k-dev", org: UUID = ORG, workspace: UUID = WORKSPACE):
    """A deterministic opaque token and its bundle entry; the token derives from the key_id so tests stay reproducible."""
    token = f"{INFERENCE_TOKEN_PREFIX}secret-{key_id}"
    return token, KeyEntry(key_id=str(key_id), org_id=org, workspace_id=workspace, token_hash=token_hash(token))


def make_bundle(keys=(), catalog=None, org=ORG):
    return BundleV1(
        bundle_id=uuid4(),
        org_id=org,
        issued_at=NOW,
        keys=list(keys),
        catalog=catalog or Catalog(providers=[], models=[]),
    )


def make_remote_bundle(key_ids=("k1",), org=ORG):
    keys = [make_key(k, org)[1] for k in key_ids]
    return make_bundle(keys=keys, org=org)


def make_config(tmp_path, outbox_kind: Literal["sqlite", "devnull"] = "sqlite") -> Config:
    control_plane = ControlPlaneLink(url=CONTROL_PLANE_URL, token="dp-token")
    outbox_config = DevNullOutboxConfig() if outbox_kind == "devnull" else SqliteOutboxConfig(control_plane=control_plane, cache_dir=tmp_path)
    return Config(
        bundle=RemoteBundleConfig(control_plane=control_plane, cache_dir=tmp_path),
        events=outbox_config,
    )


def make_outbox(tmp_path, http_client: httpx.AsyncClient, flush_interval_s: float = 5.0) -> SqliteOutbox:
    return SqliteOutbox(
        SqliteOutboxConfig(
            control_plane=ControlPlaneLink(url=CONTROL_PLANE_URL, token="dp-token"),
            cache_dir=tmp_path,
            flush_interval_s=flush_interval_s,
        ),
        http_client=http_client,
    )


def mock_control_plane() -> None:
    respx.get(f"{CONTROL_PLANE_URL}/api/v1/bundles/manifest").mock(return_value=httpx.Response(503))
    respx.post(f"{CONTROL_PLANE_URL}/api/v1/heartbeat").mock(return_value=httpx.Response(200))


PLATFORM_CREDENTIAL = make_credential(org=None)
USAGE = {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12}
CTX = Ctx(
    request_id=uuid7(),
    model=MODEL,
    provider=PROVIDER,
    stream=True,
    org_id=ORG,
    workspace_id=WORKSPACE,
    key_id="k-dev",
    credential_id=uuid7(),
    credential_scope="workspace",
    bundle_id=uuid7(),
)


def make_adapter():
    return REGISTRY["openai_compatible"](PROVIDER, Secret("sk-test"))


def sse(payload: dict) -> bytes:
    return b"data: " + json.dumps(payload, ensure_ascii=False).encode() + b"\n\n"


def delta_event(delta: dict, finish: str | None = None) -> dict:
    return {"id": "chatcmpl-9", "model": "gpt-real", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


TEXT_EVENTS = [
    delta_event({"role": "assistant"}),
    delta_event({"content": "héllo "}),
    delta_event({"content": "\U0001f30d wor"}),
    delta_event({"content": "ld"}),
    delta_event({}, finish="stop"),
    {"id": "chatcmpl-9", "model": "gpt-real", "choices": [], "usage": USAGE},
]
TEXT_LOG = b"".join(sse(e) for e in TEXT_EVENTS) + b"data: [DONE]\n\n"

TEXT_NONSTREAM = {
    "id": "chatcmpl-9",
    "model": "gpt-real",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "héllo \U0001f30d world"}, "finish_reason": "stop"}],
    "usage": USAGE,
}


@dataclass(frozen=True)
class BootedApp:
    app: Starlette
    api_key: str


@pytest.fixture
def booted(tmp_path, monkeypatch) -> BootedApp:
    """A booted-app environment: cached bundle, constructed Config, and a valid caller token.

    The config is constructed and injected through create_app, never parsed; parsing the config
    file is test_config.py's job.
    """
    caller_token, entry = make_key()
    catalog = Catalog(providers=[PROVIDER], models=[MODEL], credentials=[PLATFORM_CREDENTIAL])
    bundle = make_bundle(keys=[entry], catalog=catalog)
    write_cached_bundles(tmp_path, CachedBundles(bundles=[bundle]))
    control_plane = ControlPlaneLink(url=CONTROL_PLANE_URL, token="dp-token")
    config = Config(
        bundle=RemoteBundleConfig(control_plane=control_plane, cache_dir=tmp_path),
        events=SqliteOutboxConfig(control_plane=control_plane, cache_dir=tmp_path),
    )
    monkeypatch.setenv("P1_API_KEY", "sk-test-not-real")  # the conventional name the env store falls back to for a platform provider key
    return BootedApp(app=create_app(config), api_key=caller_token)


@pytest.fixture
def api_key(booted: BootedApp) -> str:
    return booted.api_key


@pytest.fixture
def dp_app(booted: BootedApp) -> Starlette:
    return booted.app


@pytest.fixture
async def http_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client
