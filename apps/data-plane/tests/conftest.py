from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

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
    sign_bundle,
    token_hash,
    uuid7,
)
from data_plane.adapters import REGISTRY
from data_plane.adapters.base import Ctx
from data_plane.app import create_app
from data_plane.config import BundleConfig, Config, ControlPlaneLink, EventsConfig

if TYPE_CHECKING:
    from starlette.applications import Starlette

NOW = datetime.now(tz=UTC)
ORG = uuid7()
WORKSPACE = uuid7()

UNUSED_PUBLIC_KEY = Ed25519PrivateKey.generate().public_key()

PROVIDER = ProviderEntry(provider_id="p1", kind="openai_compatible", base_url="https://api.openai.com/v1")
MODEL = ModelEntry(
    model_id="gpt-test",
    provider_id="p1",
    upstream_model="gpt-real",
    input_price_per_mtok=1.0,
    output_price_per_mtok=2.0,
    context_window=128000,
    capabilities=["streaming"],
)


def make_credential(service="p1", name="default", org=ORG, **scope) -> CredentialEntry:
    """A credential entry naming a secret.

    scope takes workspace, priority, version and secret_id. Passing secret_id describes the same
    credential twice, which is what a rotation looks like from the data plane.
    """
    ref = SecretRef(
        purpose=SecretPurpose.provider,
        service=service,
        name=name,
        secret_id=scope.get("secret_id") or uuid7(),
        org_id=org,
        workspace_id=scope.get("workspace"),
    )
    return CredentialEntry(ref=ref, priority=scope.get("priority", 100), version=scope.get("version", 1))


def make_key(key_id="k-dev", org=ORG, workspace=WORKSPACE):
    """A deterministic opaque token and its bundle entry; the token derives from the key_id so tests stay reproducible."""
    token = f"{INFERENCE_TOKEN_PREFIX}secret-{key_id}"
    return token, KeyEntry(key_id=key_id, org_id=org, workspace_id=workspace, token_hash=token_hash(token))


def make_bundle(keys=(), catalog=None, org=ORG):
    return BundleV1(
        bundle_id=uuid4(),
        org_id=org,
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=24),
        keys=list(keys),
        catalog=catalog or Catalog(providers=[], models=[]),
    )


def make_signed(private_key, key_ids=("k1",), org=ORG):
    keys = [make_key(k, org)[1] for k in key_ids]
    return sign_bundle(make_bundle(keys=keys, org=org), private_key, "k1")


def make_config(tmp_path, backend="sqlite") -> Config:
    return Config(
        control_plane=ControlPlaneLink(url="http://cp.test", token="dp-token"),
        bundle=BundleConfig(public_key=UNUSED_PUBLIC_KEY, cache_dir=tmp_path),
        events=EventsConfig(backend=backend),
    )


PLATFORM_CREDENTIAL = make_credential(org=None)
USAGE = {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12}
CTX = Ctx(request_id="req-1", model=MODEL, provider=PROVIDER, stream=True)


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
    token: str


@pytest.fixture
def booted(tmp_path, monkeypatch) -> BootedApp:
    """A booted-app environment: signed bundle on disk, an app built from a constructed Config, and a valid caller token.

    The config is constructed and injected through create_app, never parsed; parsing the config
    file is test_config.py's job.
    """
    bundle_key = Ed25519PrivateKey.generate()
    caller_token, entry = make_key()
    catalog = Catalog(providers=[PROVIDER], models=[MODEL], credentials=[PLATFORM_CREDENTIAL])
    bundle = make_bundle(keys=[entry], catalog=catalog)
    (tmp_path / "bundle.json").write_text(sign_bundle(bundle, bundle_key, "k1").model_dump_json(), encoding="utf-8")
    config = Config(bundle=BundleConfig(public_key=bundle_key.public_key(), cache_dir=tmp_path))
    monkeypatch.setenv("P1_API_KEY", "sk-test-not-real")  # the conventional name the env store falls back to for a platform provider key
    return BootedApp(app=create_app(config), token=caller_token)


@pytest.fixture
def token(booted: BootedApp) -> str:
    return booted.token


@pytest.fixture
def dp_app(booted: BootedApp) -> Starlette:
    return booted.app
