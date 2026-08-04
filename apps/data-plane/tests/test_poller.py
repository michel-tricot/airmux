from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import respx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from contract import BundleV1, Catalog, KeyEntry, sign_bundle
from data_plane.cache import read_cached_bundle
from data_plane.config import Config
from data_plane.holder import BundleHolder
from data_plane.poller import poll_once

NOW = datetime.now(tz=UTC)


def make_signed(private_key, key_ids=("k1",), revocations=()):
    bundle = BundleV1(
        bundle_id=uuid4(),
        org_id="o1",
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=24),
        keys=[KeyEntry(key_id=k, org_id="o1", allowed_models=["*"]) for k in key_ids],
        revocations=list(revocations),
        catalog=Catalog(providers=[], models=[]),
    )
    return sign_bundle(bundle, private_key, "k1")


def make_config(tmp_path):
    return Config(
        control_plane_url="http://cp.test",
        dp_token="dp-token",  # noqa: S106 test fixture, not a secret
        bundle_public_key_b64="unused-here",
        cache_dir=tmp_path,
        staleness_policy="serve_and_warn",
    )


@respx.mock
async def test_poll_swaps_and_persists(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    signed = make_signed(private_key)
    respx.get("http://cp.test/v1/bundle/latest").mock(return_value=httpx.Response(200, content=signed.model_dump_json()))
    holder = BundleHolder()
    await poll_once(make_config(tmp_path), holder, private_key.public_key())
    assert holder.current is not None
    assert holder.current.bundle_id == signed.payload.bundle_id
    assert "k1" in holder.key_index
    cached = read_cached_bundle(tmp_path)
    assert cached is not None
    assert cached.payload.bundle_id == signed.payload.bundle_id


@respx.mock
async def test_poll_same_bundle_is_a_noop(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    signed = make_signed(private_key)
    respx.get("http://cp.test/v1/bundle/latest").mock(return_value=httpx.Response(200, content=signed.model_dump_json()))
    holder = BundleHolder()
    config = make_config(tmp_path)
    await poll_once(config, holder, private_key.public_key())
    (tmp_path / "bundle.json").unlink()
    await poll_once(config, holder, private_key.public_key())
    assert not (tmp_path / "bundle.json").exists()


@respx.mock
async def test_poll_revocation_updates_holder(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    first = make_signed(private_key, key_ids=("k1",))
    second = make_signed(private_key, key_ids=(), revocations=("k1",))
    route = respx.get("http://cp.test/v1/bundle/latest").mock(return_value=httpx.Response(200, content=first.model_dump_json()))
    holder = BundleHolder()
    config = make_config(tmp_path)
    await poll_once(config, holder, private_key.public_key())
    assert "k1" in holder.key_index
    route.mock(return_value=httpx.Response(200, content=second.model_dump_json()))
    await poll_once(config, holder, private_key.public_key())
    assert holder.key_index == {}
    assert "k1" in holder.revocations
