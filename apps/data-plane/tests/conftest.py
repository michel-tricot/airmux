from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from contract import BundleV1, Catalog, KeyEntry, ModelEntry, ProviderEntry, mint_api_token, public_key_to_b64, sign_bundle
from data_plane.adapters import REGISTRY
from data_plane.canonical import Ctx
from data_plane.config import AuthConfig, BundleConfig, Config, ControlPlaneLink, EventsConfig

NOW = datetime.now(tz=UTC)

PROVIDER = ProviderEntry(provider_id="p1", kind="openai_compatible", base_url="https://api.openai.com/v1", credential_ref="env:OPENAI_API_KEY")
MODEL = ModelEntry(
    model_id="gpt-test",
    provider_id="p1",
    upstream_model="gpt-real",
    input_price_per_mtok=1.0,
    output_price_per_mtok=2.0,
    context_window=128000,
    capabilities=["streaming"],
)
CTX = Ctx(request_id="req-1", model=MODEL, provider=PROVIDER, stream=True)
USAGE = {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12}


def make_adapter():
    return REGISTRY["openai_compatible"](PROVIDER)


def make_bundle(keys=(), revocations=(), catalog=None, org="org-dev"):
    return BundleV1(
        bundle_id=uuid4(),
        org_id=org,
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=24),
        keys=list(keys),
        revocations=list(revocations),
        catalog=catalog or Catalog(providers=[], models=[]),
    )


def make_signed(private_key, key_ids=("k1",), revocations=(), org="o1"):
    keys = [KeyEntry(key_id=k, org_id=org, allowed_models=["*"]) for k in key_ids]
    return sign_bundle(make_bundle(keys=keys, revocations=revocations, org=org), private_key, "k1")


def make_config(tmp_path, backend="sqlite") -> Config:
    return Config(
        control_plane=ControlPlaneLink(url="http://cp.test", token="dp-token"),  # noqa: S106 test fixture, not a secret
        bundle=BundleConfig(public_key="unused", cache_dir=tmp_path),
        auth=AuthConfig(token_public_key="unused"),  # noqa: S106 a public key, not a secret
        events=EventsConfig(backend=backend),
    )


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


@pytest.fixture
def token(tmp_path, monkeypatch):
    """A booted-app environment: signed bundle on disk, config file, and a valid caller token."""
    bundle_key = Ed25519PrivateKey.generate()
    token_key = Ed25519PrivateKey.generate()
    bundle = make_bundle(
        keys=[KeyEntry(key_id="k-dev", org_id="org-dev", allowed_models=["*"])],
        catalog=Catalog(providers=[PROVIDER], models=[MODEL]),
    )
    (tmp_path / "bundle.json").write_text(sign_bundle(bundle, bundle_key, "k1").model_dump_json(), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GW_CONFIG", raising=False)
    config = (
        f'data_plane:\n  bundle:\n    public_key: "{public_key_to_b64(bundle_key.public_key())}"\n    cache_dir: {tmp_path}\n'
        f'  auth:\n    token_public_key: "{public_key_to_b64(token_key.public_key())}"\n'
    )
    (tmp_path / "airllm.yml").write_text(config, encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    return mint_api_token("k-dev", "org-dev", token_key, NOW)
