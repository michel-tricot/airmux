from __future__ import annotations

import httpx
import pytest
import respx
from conftest import ORG, make_config, make_key, make_signed
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from contract import BundleManifest, BundleManifestEntry, uuid7
from data_plane.bundle import BundleHolder, RemoteBundleConfig
from data_plane.bundle.remote import RemoteBundleSource
from data_plane.cache import read_cached_bundles


def _source(tmp_path):
    config = make_config(tmp_path)
    assert isinstance(config.bundle, RemoteBundleConfig)
    return config.bundle


def _remote_source(tmp_path, holder, private_key, http_client) -> RemoteBundleSource:
    bundle_config = _source(tmp_path)
    bundle_config = bundle_config.model_copy(update={"verify_key": private_key.public_key()})
    return RemoteBundleSource(bundle_config, holder, http_client)


def manifest_response(*signed) -> httpx.Response:
    entries = [
        BundleManifestEntry(
            org_id=bundle.payload.org_id,
            bundle_id=bundle.payload.bundle_id,
        )
        for bundle in signed
    ]
    return httpx.Response(200, content=f'{{"data": {BundleManifest(bundles=entries).model_dump_json()}}}')


def bundle_response(signed) -> httpx.Response:
    return httpx.Response(200, content=f'{{"data": {signed.model_dump_json()}}}')


@respx.mock
async def test_poll_admits_every_bundle_in_the_authorized_manifest(tmp_path, http_client):
    private_key = Ed25519PrivateKey.generate()
    other_org = uuid7()
    first = make_signed(private_key, key_ids=("first",), org=ORG)
    second = make_signed(private_key, key_ids=("second",), org=other_org)
    respx.get("http://cp.test/api/v1/bundles/manifest").mock(return_value=manifest_response(first, second))
    respx.get(f"http://cp.test/api/v1/bundles/{first.payload.bundle_id}").mock(return_value=bundle_response(first))
    respx.get(f"http://cp.test/api/v1/bundles/{second.payload.bundle_id}").mock(return_value=bundle_response(second))
    holder = BundleHolder()

    await _remote_source(tmp_path, holder, private_key, http_client).once()

    assert set(holder.current.snapshots) == {ORG, other_org}
    assert make_key("first", ORG)[1].token_hash in holder.current.key_index
    assert make_key("second", other_org)[1].token_hash in holder.current.key_index
    cached = read_cached_bundles(tmp_path)
    assert cached is not None
    assert {bundle.payload.bundle_id for bundle in cached} == {first.payload.bundle_id, second.payload.bundle_id}


@respx.mock
async def test_poll_swaps_and_persists(tmp_path, http_client):
    private_key = Ed25519PrivateKey.generate()
    signed = make_signed(private_key)
    respx.get("http://cp.test/api/v1/bundles/manifest").mock(return_value=manifest_response(signed))
    respx.get(f"http://cp.test/api/v1/bundles/{signed.payload.bundle_id}").mock(return_value=bundle_response(signed))
    holder = BundleHolder()
    await _remote_source(tmp_path, holder, private_key, http_client).once()
    assert holder.current.snapshots[ORG].bundle.bundle_id == signed.payload.bundle_id
    assert make_key("k1")[1].token_hash in holder.current.key_index
    cached = read_cached_bundles(tmp_path)
    assert cached is not None
    assert [bundle.payload.bundle_id for bundle in cached] == [signed.payload.bundle_id]


@respx.mock
async def test_poll_does_not_publish_a_bundle_set_that_failed_to_persist(tmp_path, http_client, monkeypatch):
    private_key = Ed25519PrivateKey.generate()
    signed = make_signed(private_key)
    respx.get("http://cp.test/api/v1/bundles/manifest").mock(return_value=manifest_response(signed))
    respx.get(f"http://cp.test/api/v1/bundles/{signed.payload.bundle_id}").mock(return_value=bundle_response(signed))
    holder = BundleHolder()
    error = OSError("cache unavailable")

    def fail_write(*_args):
        raise error

    monkeypatch.setattr("data_plane.bundle.remote.write_cached_bundles", fail_write)

    with pytest.raises(OSError, match="cache unavailable"):
        await _remote_source(tmp_path, holder, private_key, http_client).once()

    assert holder.current.snapshots == {}


@respx.mock
async def test_poll_same_bundle_is_a_noop(tmp_path, http_client):
    private_key = Ed25519PrivateKey.generate()
    signed = make_signed(private_key)
    respx.get("http://cp.test/api/v1/bundles/manifest").mock(return_value=manifest_response(signed))
    respx.get(f"http://cp.test/api/v1/bundles/{signed.payload.bundle_id}").mock(return_value=bundle_response(signed))
    holder = BundleHolder()
    source = _remote_source(tmp_path, holder, private_key, http_client)
    await source.once()
    (tmp_path / "bundles.json").unlink()
    await source.once()
    assert not (tmp_path / "bundles.json").exists()


@respx.mock
async def test_poll_revocation_updates_holder(tmp_path, http_client):
    private_key = Ed25519PrivateKey.generate()
    first = make_signed(private_key, key_ids=("k1",))
    second = make_signed(private_key, key_ids=())
    route = respx.get("http://cp.test/api/v1/bundles/manifest").mock(return_value=manifest_response(first))
    respx.get(f"http://cp.test/api/v1/bundles/{first.payload.bundle_id}").mock(return_value=bundle_response(first))
    respx.get(f"http://cp.test/api/v1/bundles/{second.payload.bundle_id}").mock(return_value=bundle_response(second))
    holder = BundleHolder()
    source = _remote_source(tmp_path, holder, private_key, http_client)
    await source.once()
    assert make_key("k1")[1].token_hash in holder.current.key_index
    route.mock(return_value=manifest_response(second))
    await source.once()
    assert holder.current.key_index == {}


@respx.mock
async def test_poll_signature_failure_identifies_the_bundle_and_signing_key(tmp_path, http_client):
    signing_key = Ed25519PrivateKey.generate()
    verify_key = Ed25519PrivateKey.generate()
    signed = make_signed(signing_key)
    respx.get("http://cp.test/api/v1/bundles/manifest").mock(return_value=manifest_response(signed))
    respx.get(f"http://cp.test/api/v1/bundles/{signed.payload.bundle_id}").mock(return_value=bundle_response(signed))
    holder = BundleHolder()

    with pytest.raises(InvalidSignature) as error:
        await _remote_source(tmp_path, holder, verify_key, http_client).once()

    message = str(error.value)
    assert str(signed.payload.bundle_id) in message
    assert signed.signing_key_id in message
    assert holder.current.snapshots == {}
    assert read_cached_bundles(tmp_path) is None


@respx.mock
async def test_poll_removes_an_org_absent_from_the_next_manifest(tmp_path, http_client):
    private_key = Ed25519PrivateKey.generate()
    other_org = uuid7()
    first = make_signed(private_key, key_ids=("first",), org=ORG)
    second = make_signed(private_key, key_ids=("second",), org=other_org)
    manifest = respx.get("http://cp.test/api/v1/bundles/manifest").mock(return_value=manifest_response(first, second))
    respx.get(f"http://cp.test/api/v1/bundles/{first.payload.bundle_id}").mock(return_value=bundle_response(first))
    respx.get(f"http://cp.test/api/v1/bundles/{second.payload.bundle_id}").mock(return_value=bundle_response(second))
    holder = BundleHolder()
    source = _remote_source(tmp_path, holder, private_key, http_client)
    await source.once()

    manifest.mock(return_value=manifest_response(first))
    await source.once()

    assert list(holder.current.snapshots) == [ORG]
    assert make_key("second", other_org)[1].token_hash not in holder.current.key_index
    cached = read_cached_bundles(tmp_path)
    assert cached is not None
    assert [bundle.payload.org_id for bundle in cached] == [ORG]


@respx.mock
async def test_poll_fetches_only_the_org_whose_bundle_changed(tmp_path, http_client):
    private_key = Ed25519PrivateKey.generate()
    other_org = uuid7()
    first = make_signed(private_key, key_ids=("first",), org=ORG)
    changed = make_signed(private_key, key_ids=("changed",), org=ORG)
    second = make_signed(private_key, key_ids=("second",), org=other_org)
    manifest = respx.get("http://cp.test/api/v1/bundles/manifest").mock(return_value=manifest_response(first, second))
    first_fetch = respx.get(f"http://cp.test/api/v1/bundles/{first.payload.bundle_id}").mock(return_value=bundle_response(first))
    changed_fetch = respx.get(f"http://cp.test/api/v1/bundles/{changed.payload.bundle_id}").mock(return_value=bundle_response(changed))
    second_fetch = respx.get(f"http://cp.test/api/v1/bundles/{second.payload.bundle_id}").mock(return_value=bundle_response(second))
    holder = BundleHolder()
    source = _remote_source(tmp_path, holder, private_key, http_client)
    await source.once()

    manifest.mock(return_value=manifest_response(changed, second))
    await source.once()

    assert first_fetch.call_count == 1
    assert changed_fetch.call_count == 1
    assert second_fetch.call_count == 1
    assert make_key("changed", ORG)[1].token_hash in holder.current.key_index
    assert make_key("second", other_org)[1].token_hash in holder.current.key_index


@respx.mock
async def test_poll_rejects_a_bundle_that_does_not_match_its_manifest_entry(tmp_path, http_client):
    private_key = Ed25519PrivateKey.generate()
    expected = make_signed(private_key, key_ids=("expected",))
    mismatched = make_signed(private_key, key_ids=("mismatched",))
    respx.get("http://cp.test/api/v1/bundles/manifest").mock(return_value=manifest_response(expected))
    respx.get(f"http://cp.test/api/v1/bundles/{expected.payload.bundle_id}").mock(return_value=bundle_response(mismatched))
    holder = BundleHolder()

    with pytest.raises(ValueError, match="does not match manifest entry"):
        await _remote_source(tmp_path, holder, private_key, http_client).once()

    assert holder.current.snapshots == {}
    assert read_cached_bundles(tmp_path) is None


@respx.mock
async def test_poll_rejects_a_token_hash_shared_by_two_org_bundles(tmp_path, http_client):
    private_key = Ed25519PrivateKey.generate()
    other_org = uuid7()
    first = make_signed(private_key, key_ids=("same",), org=ORG)
    second = make_signed(private_key, key_ids=("same",), org=other_org)
    respx.get("http://cp.test/api/v1/bundles/manifest").mock(return_value=manifest_response(first, second))
    respx.get(f"http://cp.test/api/v1/bundles/{first.payload.bundle_id}").mock(return_value=bundle_response(first))
    respx.get(f"http://cp.test/api/v1/bundles/{second.payload.bundle_id}").mock(return_value=bundle_response(second))
    holder = BundleHolder()

    with pytest.raises(ValueError, match="token hash appears in more than one bundle"):
        await _remote_source(tmp_path, holder, private_key, http_client).once()

    assert holder.current.snapshots == {}
    assert read_cached_bundles(tmp_path) is None
