from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
import respx
from conftest import ORG, make_config, make_key, make_remote_bundle
from pydantic import ValidationError
from starlette.requests import Request

from contract import BundleManifest, BundleManifestEntry, BundleV1, uuid7
from data_plane.app import readyz
from data_plane.bundle import BundleHolder, RemoteBundleConfig
from data_plane.bundle.holder import BundleSet
from data_plane.bundle.remote import RemoteBundleSource
from data_plane.cache import read_cached_bundles
from data_plane.metrics import DataPlaneMetrics


def _source(tmp_path):
    config = make_config(tmp_path)
    assert isinstance(config.bundle, RemoteBundleConfig)
    return config.bundle


def _remote_source(tmp_path, holder, http_client) -> RemoteBundleSource:
    return RemoteBundleSource(_source(tmp_path), holder, http_client)


def manifest_response(*bundles: BundleV1) -> httpx.Response:
    entries = [BundleManifestEntry(org_id=bundle.org_id, bundle_id=bundle.bundle_id) for bundle in bundles]
    return httpx.Response(200, content=f'{{"data": {BundleManifest(bundles=entries).model_dump_json()}}}')


def bundle_response(bundle: BundleV1) -> httpx.Response:
    return httpx.Response(200, content=f'{{"data": {bundle.model_dump_json()}}}')


@respx.mock
async def test_poll_admits_every_bundle_in_the_authorized_manifest(tmp_path, http_client):
    other_org = uuid7()
    first = make_remote_bundle(key_ids=("first",), org=ORG)
    second = make_remote_bundle(key_ids=("second",), org=other_org)
    respx.get("http://cp.test/api/v1/bundles/manifest").mock(return_value=manifest_response(first, second))
    respx.get(f"http://cp.test/api/v1/bundles/{first.bundle_id}").mock(return_value=bundle_response(first))
    respx.get(f"http://cp.test/api/v1/bundles/{second.bundle_id}").mock(return_value=bundle_response(second))
    holder = BundleHolder(DataPlaneMetrics())

    await _remote_source(tmp_path, holder, http_client).once()

    assert set(holder.current.snapshots) == {ORG, other_org}
    assert make_key("first", ORG)[1].token_hash in holder.current.key_index
    assert make_key("second", other_org)[1].token_hash in holder.current.key_index
    cached = read_cached_bundles(tmp_path)
    assert cached is not None
    assert {bundle.bundle_id for bundle in cached.bundles} == {first.bundle_id, second.bundle_id}


@respx.mock
async def test_poll_swaps_and_persists(tmp_path, http_client):
    bundle = make_remote_bundle()
    respx.get("http://cp.test/api/v1/bundles/manifest").mock(return_value=manifest_response(bundle))
    respx.get(f"http://cp.test/api/v1/bundles/{bundle.bundle_id}").mock(return_value=bundle_response(bundle))
    holder = BundleHolder(DataPlaneMetrics())

    await _remote_source(tmp_path, holder, http_client).once()

    assert holder.current.snapshots[ORG].bundle.bundle_id == bundle.bundle_id
    assert make_key("k1")[1].token_hash in holder.current.key_index
    cached = read_cached_bundles(tmp_path)
    assert cached is not None
    assert [cached_bundle.bundle_id for cached_bundle in cached.bundles] == [bundle.bundle_id]


@respx.mock
async def test_cached_bundle_keeps_serving_when_control_plane_is_unreachable(tmp_path, http_client):
    bundle = make_remote_bundle()
    respx.get("http://cp.test/api/v1/bundles/manifest").mock(return_value=manifest_response(bundle))
    respx.get(f"http://cp.test/api/v1/bundles/{bundle.bundle_id}").mock(return_value=bundle_response(bundle))
    first_holder = BundleHolder(DataPlaneMetrics())
    await _remote_source(tmp_path, first_holder, http_client).once()

    restarted_holder = BundleHolder(DataPlaneMetrics())
    _remote_source(tmp_path, restarted_holder, http_client)._load_cached()

    assert restarted_holder.current.snapshots[ORG].bundle.bundle_id == bundle.bundle_id


@respx.mock
async def test_poll_does_not_publish_a_bundle_set_that_failed_to_persist(tmp_path, http_client, monkeypatch):
    bundle = make_remote_bundle()
    respx.get("http://cp.test/api/v1/bundles/manifest").mock(return_value=manifest_response(bundle))
    respx.get(f"http://cp.test/api/v1/bundles/{bundle.bundle_id}").mock(return_value=bundle_response(bundle))
    holder = BundleHolder(DataPlaneMetrics())
    error = OSError("cache unavailable")

    def fail_write(*_args):
        raise error

    monkeypatch.setattr("data_plane.bundle.remote.write_cached_bundles", fail_write)

    with pytest.raises(OSError, match="cache unavailable"):
        await _remote_source(tmp_path, holder, http_client).once()

    assert holder.current.snapshots == {}


@respx.mock
async def test_poll_same_bundle_is_a_noop(tmp_path, http_client):
    bundle = make_remote_bundle()
    respx.get("http://cp.test/api/v1/bundles/manifest").mock(return_value=manifest_response(bundle))
    respx.get(f"http://cp.test/api/v1/bundles/{bundle.bundle_id}").mock(return_value=bundle_response(bundle))
    holder = BundleHolder(DataPlaneMetrics())
    source = _remote_source(tmp_path, holder, http_client)
    await source.once()
    (tmp_path / "bundles.json").unlink()

    await source.once()

    assert not (tmp_path / "bundles.json").exists()


@respx.mock
async def test_poll_revocation_updates_holder(tmp_path, http_client):
    first = make_remote_bundle(key_ids=("k1",))
    second = make_remote_bundle(key_ids=())
    route = respx.get("http://cp.test/api/v1/bundles/manifest").mock(return_value=manifest_response(first))
    respx.get(f"http://cp.test/api/v1/bundles/{first.bundle_id}").mock(return_value=bundle_response(first))
    respx.get(f"http://cp.test/api/v1/bundles/{second.bundle_id}").mock(return_value=bundle_response(second))
    holder = BundleHolder(DataPlaneMetrics())
    source = _remote_source(tmp_path, holder, http_client)
    await source.once()
    assert make_key("k1")[1].token_hash in holder.current.key_index

    route.mock(return_value=manifest_response(second))
    await source.once()

    assert holder.current.key_index == {}


@respx.mock
async def test_poll_rejects_a_bundle_that_fails_schema_validation(tmp_path, http_client):
    bundle = make_remote_bundle()
    respx.get("http://cp.test/api/v1/bundles/manifest").mock(return_value=manifest_response(bundle))
    respx.get(f"http://cp.test/api/v1/bundles/{bundle.bundle_id}").mock(return_value=httpx.Response(200, json={"data": {"schema_version": 1}}))
    metrics = DataPlaneMetrics()
    holder = BundleHolder(metrics)

    with pytest.raises(ValidationError):
        await _remote_source(tmp_path, holder, http_client).once()

    assert "airmux_data_plane_bundle_manifest_rejected 1.0" in metrics.render().decode()
    assert holder.current.snapshots == {}
    assert read_cached_bundles(tmp_path) is None


async def test_readiness_keeps_serving_after_rejecting_a_new_manifest():
    holder = BundleHolder(DataPlaneMetrics())
    holder.swap(BundleSet.from_bundles((make_remote_bundle(),)), "cached")
    request = Request({"type": "http"})
    request.state.runtime = SimpleNamespace(holder=holder, outbox=SimpleNamespace(accepting=True))

    assert (await readyz(request)).status_code == 200
    holder.reject_manifest()

    assert (await readyz(request)).status_code == 200


async def test_readiness_fails_when_metering_cannot_accept_work():
    holder = BundleHolder(DataPlaneMetrics())
    holder.swap(BundleSet.from_bundles((make_remote_bundle(),)), "cached")
    request = Request({"type": "http"})
    request.state.runtime = SimpleNamespace(holder=holder, outbox=SimpleNamespace(accepting=False))

    assert (await readyz(request)).status_code == 503


@respx.mock
async def test_poll_removes_an_org_absent_from_the_next_manifest(tmp_path, http_client):
    other_org = uuid7()
    first = make_remote_bundle(key_ids=("first",), org=ORG)
    second = make_remote_bundle(key_ids=("second",), org=other_org)
    manifest = respx.get("http://cp.test/api/v1/bundles/manifest").mock(return_value=manifest_response(first, second))
    respx.get(f"http://cp.test/api/v1/bundles/{first.bundle_id}").mock(return_value=bundle_response(first))
    respx.get(f"http://cp.test/api/v1/bundles/{second.bundle_id}").mock(return_value=bundle_response(second))
    holder = BundleHolder(DataPlaneMetrics())
    source = _remote_source(tmp_path, holder, http_client)
    await source.once()

    manifest.mock(return_value=manifest_response(first))
    await source.once()

    assert list(holder.current.snapshots) == [ORG]
    assert make_key("second", other_org)[1].token_hash not in holder.current.key_index
    cached = read_cached_bundles(tmp_path)
    assert cached is not None
    assert [bundle.org_id for bundle in cached.bundles] == [ORG]


@respx.mock
async def test_poll_fetches_only_the_org_whose_bundle_changed(tmp_path, http_client):
    other_org = uuid7()
    first = make_remote_bundle(key_ids=("first",), org=ORG)
    changed = make_remote_bundle(key_ids=("changed",), org=ORG)
    second = make_remote_bundle(key_ids=("second",), org=other_org)
    manifest = respx.get("http://cp.test/api/v1/bundles/manifest").mock(return_value=manifest_response(first, second))
    first_fetch = respx.get(f"http://cp.test/api/v1/bundles/{first.bundle_id}").mock(return_value=bundle_response(first))
    changed_fetch = respx.get(f"http://cp.test/api/v1/bundles/{changed.bundle_id}").mock(return_value=bundle_response(changed))
    second_fetch = respx.get(f"http://cp.test/api/v1/bundles/{second.bundle_id}").mock(return_value=bundle_response(second))
    holder = BundleHolder(DataPlaneMetrics())
    source = _remote_source(tmp_path, holder, http_client)
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
    expected = make_remote_bundle(key_ids=("expected",))
    mismatched = make_remote_bundle(key_ids=("mismatched",))
    respx.get("http://cp.test/api/v1/bundles/manifest").mock(return_value=manifest_response(expected))
    respx.get(f"http://cp.test/api/v1/bundles/{expected.bundle_id}").mock(return_value=bundle_response(mismatched))
    holder = BundleHolder(DataPlaneMetrics())

    with pytest.raises(ValueError, match="does not match manifest entry"):
        await _remote_source(tmp_path, holder, http_client).once()

    assert holder.current.snapshots == {}
    assert read_cached_bundles(tmp_path) is None


@respx.mock
async def test_poll_rejects_a_token_hash_shared_by_two_org_bundles(tmp_path, http_client):
    other_org = uuid7()
    first = make_remote_bundle(key_ids=("same",), org=ORG)
    second = make_remote_bundle(key_ids=("same",), org=other_org)
    respx.get("http://cp.test/api/v1/bundles/manifest").mock(return_value=manifest_response(first, second))
    respx.get(f"http://cp.test/api/v1/bundles/{first.bundle_id}").mock(return_value=bundle_response(first))
    respx.get(f"http://cp.test/api/v1/bundles/{second.bundle_id}").mock(return_value=bundle_response(second))
    holder = BundleHolder(DataPlaneMetrics())

    with pytest.raises(ValueError, match="token hash appears in more than one bundle"):
        await _remote_source(tmp_path, holder, http_client).once()

    assert holder.current.snapshots == {}
    assert read_cached_bundles(tmp_path) is None
