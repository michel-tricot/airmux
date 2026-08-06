from __future__ import annotations

import httpx
import respx
from conftest import make_config, make_key, make_signed
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from data_plane.cache import read_cached_bundle
from data_plane.holder import BundleHolder
from data_plane.poller import poll_once


def enveloped(signed) -> str:
    return f'{{"data": {signed.model_dump_json()}}}'


@respx.mock
async def test_poll_swaps_and_persists(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    signed = make_signed(private_key)
    respx.get("http://cp.test/v1/bundle/latest").mock(return_value=httpx.Response(200, content=enveloped(signed)))
    holder = BundleHolder()
    await poll_once(make_config(tmp_path), holder, private_key.public_key())
    assert holder.snapshot is not None
    assert holder.snapshot.bundle.bundle_id == signed.payload.bundle_id
    assert make_key("k1", org="o1")[1].token_hash in holder.snapshot.key_index
    cached = read_cached_bundle(tmp_path)
    assert cached is not None
    assert cached.payload.bundle_id == signed.payload.bundle_id


@respx.mock
async def test_poll_same_bundle_is_a_noop(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    signed = make_signed(private_key)
    respx.get("http://cp.test/v1/bundle/latest").mock(return_value=httpx.Response(200, content=enveloped(signed)))
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
    second = make_signed(private_key, key_ids=())
    route = respx.get("http://cp.test/v1/bundle/latest").mock(return_value=httpx.Response(200, content=enveloped(first)))
    holder = BundleHolder()
    config = make_config(tmp_path)
    await poll_once(config, holder, private_key.public_key())
    assert holder.snapshot is not None
    assert make_key("k1", org="o1")[1].token_hash in holder.snapshot.key_index
    route.mock(return_value=httpx.Response(200, content=enveloped(second)))
    await poll_once(config, holder, private_key.public_key())
    assert holder.snapshot.key_index == {}
