from __future__ import annotations

import httpx
import pytest
import respx
from conftest import make_config, make_key, make_signed
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from data_plane.bundle import BundleHolder, RemoteBundleConfig
from data_plane.bundle.remote import RemoteBundleSource
from data_plane.cache import read_cached_bundle


def _source(tmp_path):
    config = make_config(tmp_path)
    assert isinstance(config.bundle, RemoteBundleConfig)
    return config.bundle


def _remote_source(tmp_path, holder, private_key, http_client) -> RemoteBundleSource:
    bundle_config = _source(tmp_path)
    bundle_config = bundle_config.model_copy(update={"verify_key": private_key.public_key()})
    return RemoteBundleSource(bundle_config, holder, http_client)


def enveloped(signed) -> str:
    return f'{{"data": {signed.model_dump_json()}}}'


@respx.mock
async def test_poll_swaps_and_persists(tmp_path, http_client):
    private_key = Ed25519PrivateKey.generate()
    signed = make_signed(private_key)
    respx.get("http://cp.test/v1/bundle/latest").mock(return_value=httpx.Response(200, content=enveloped(signed)))
    holder = BundleHolder()
    await _remote_source(tmp_path, holder, private_key, http_client).once()
    assert holder.snapshot is not None
    assert holder.snapshot.bundle.bundle_id == signed.payload.bundle_id
    assert make_key("k1")[1].token_hash in holder.snapshot.key_index
    cached = read_cached_bundle(tmp_path)
    assert cached is not None
    assert cached.payload.bundle_id == signed.payload.bundle_id


@respx.mock
async def test_poll_same_bundle_is_a_noop(tmp_path, http_client):
    private_key = Ed25519PrivateKey.generate()
    signed = make_signed(private_key)
    respx.get("http://cp.test/v1/bundle/latest").mock(return_value=httpx.Response(200, content=enveloped(signed)))
    holder = BundleHolder()
    source = _remote_source(tmp_path, holder, private_key, http_client)
    await source.once()
    (tmp_path / "bundle.json").unlink()
    await source.once()
    assert not (tmp_path / "bundle.json").exists()


@respx.mock
async def test_poll_revocation_updates_holder(tmp_path, http_client):
    private_key = Ed25519PrivateKey.generate()
    first = make_signed(private_key, key_ids=("k1",))
    second = make_signed(private_key, key_ids=())
    route = respx.get("http://cp.test/v1/bundle/latest").mock(return_value=httpx.Response(200, content=enveloped(first)))
    holder = BundleHolder()
    source = _remote_source(tmp_path, holder, private_key, http_client)
    await source.once()
    assert holder.snapshot is not None
    assert make_key("k1")[1].token_hash in holder.snapshot.key_index
    route.mock(return_value=httpx.Response(200, content=enveloped(second)))
    await source.once()
    assert holder.snapshot.key_index == {}


@respx.mock
async def test_poll_signature_failure_identifies_the_bundle_and_signing_key(tmp_path, http_client):
    signing_key = Ed25519PrivateKey.generate()
    verify_key = Ed25519PrivateKey.generate()
    signed = make_signed(signing_key)
    respx.get("http://cp.test/v1/bundle/latest").mock(return_value=httpx.Response(200, content=enveloped(signed)))
    holder = BundleHolder()

    with pytest.raises(InvalidSignature) as error:
        await _remote_source(tmp_path, holder, verify_key, http_client).once()

    message = str(error.value)
    assert str(signed.payload.bundle_id) in message
    assert signed.signing_key_id in message
    assert holder.snapshot is None
    assert read_cached_bundle(tmp_path) is None
