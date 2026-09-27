from __future__ import annotations

from types import SimpleNamespace

import pytest
from aioresponses import CallbackResult
from conftest import ORG, make_config, make_key, make_remote_bundle
from pydantic import ValidationError
from starlette.requests import Request
from yarl import URL

from contract import BundleManifest, BundleManifestEntry, BundleV1, uuid7
from data_plane.app import healthz
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


def manifest_response(*bundles: BundleV1) -> CallbackResult:
    entries = [BundleManifestEntry(org_id=bundle.org_id, bundle_id=bundle.bundle_id) for bundle in bundles]
    return CallbackResult(status=200, body=f'{{"data": {BundleManifest(bundles=tuple(entries)).model_dump_json()}}}')


def bundle_response(bundle: BundleV1) -> CallbackResult:
    return CallbackResult(status=200, body=f'{{"data": {bundle.model_dump_json()}}}')


async def test_poll_admits_every_bundle_in_the_authorized_manifest(http_mock, tmp_path, http_client):
    other_org = uuid7()
    first = make_remote_bundle(key_ids=("first",), org=ORG)
    second = make_remote_bundle(key_ids=("second",), org=other_org)
    http_mock.get("http://cp.test/api/v1/bundles/manifest", callback=lambda _url, **_kwargs: manifest_response(first, second), repeat=True)
    http_mock.get(f"http://cp.test/api/v1/bundles/{first.bundle_id}", callback=lambda _url, **_kwargs: bundle_response(first), repeat=True)
    http_mock.get(f"http://cp.test/api/v1/bundles/{second.bundle_id}", callback=lambda _url, **_kwargs: bundle_response(second), repeat=True)
    holder = BundleHolder(DataPlaneMetrics())

    await _remote_source(tmp_path, holder, http_client).once()

    assert set(holder.current.snapshots) == {ORG, other_org}
    assert make_key("first", ORG)[1].token_hash in holder.current.key_index
    assert make_key("second", other_org)[1].token_hash in holder.current.key_index
    cached = read_cached_bundles(tmp_path)
    assert cached is not None
    assert {bundle.bundle_id for bundle in cached.bundles} == {first.bundle_id, second.bundle_id}


async def test_poll_swaps_and_persists(http_mock, tmp_path, http_client):
    bundle = make_remote_bundle()
    http_mock.get("http://cp.test/api/v1/bundles/manifest", callback=lambda _url, **_kwargs: manifest_response(bundle), repeat=True)
    http_mock.get(f"http://cp.test/api/v1/bundles/{bundle.bundle_id}", callback=lambda _url, **_kwargs: bundle_response(bundle), repeat=True)
    holder = BundleHolder(DataPlaneMetrics())

    await _remote_source(tmp_path, holder, http_client).once()

    assert holder.current.snapshots[ORG].bundle.bundle_id == bundle.bundle_id
    assert make_key("k1")[1].token_hash in holder.current.key_index
    cached = read_cached_bundles(tmp_path)
    assert cached is not None
    assert [cached_bundle.bundle_id for cached_bundle in cached.bundles] == [bundle.bundle_id]


async def test_cached_bundle_keeps_serving_when_control_plane_is_unreachable(http_mock, tmp_path, http_client):
    bundle = make_remote_bundle()
    http_mock.get("http://cp.test/api/v1/bundles/manifest", callback=lambda _url, **_kwargs: manifest_response(bundle), repeat=True)
    http_mock.get(f"http://cp.test/api/v1/bundles/{bundle.bundle_id}", callback=lambda _url, **_kwargs: bundle_response(bundle), repeat=True)
    first_holder = BundleHolder(DataPlaneMetrics())
    await _remote_source(tmp_path, first_holder, http_client).once()

    restarted_holder = BundleHolder(DataPlaneMetrics())
    _remote_source(tmp_path, restarted_holder, http_client)._load_cached()

    assert restarted_holder.current.snapshots[ORG].bundle.bundle_id == bundle.bundle_id
    request = Request({"type": "http"})
    request.state.runtime = SimpleNamespace(holder=restarted_holder, outbox=SimpleNamespace(accepting=True))
    assert (await healthz(request)).status_code == 200


async def test_poll_does_not_publish_a_bundle_set_that_failed_to_persist(http_mock, tmp_path, http_client, monkeypatch):
    bundle = make_remote_bundle()
    http_mock.get("http://cp.test/api/v1/bundles/manifest", callback=lambda _url, **_kwargs: manifest_response(bundle), repeat=True)
    http_mock.get(f"http://cp.test/api/v1/bundles/{bundle.bundle_id}", callback=lambda _url, **_kwargs: bundle_response(bundle), repeat=True)
    holder = BundleHolder(DataPlaneMetrics())
    error = OSError("cache unavailable")

    def fail_write(*_args):
        raise error

    monkeypatch.setattr("data_plane.bundle.remote.write_cached_bundles", fail_write)

    with pytest.raises(OSError, match="cache unavailable"):
        await _remote_source(tmp_path, holder, http_client).once()

    assert holder.current.snapshots == {}


async def test_poll_same_bundle_is_a_noop(http_mock, tmp_path, http_client):
    bundle = make_remote_bundle()
    http_mock.get("http://cp.test/api/v1/bundles/manifest", callback=lambda _url, **_kwargs: manifest_response(bundle), repeat=True)
    http_mock.get(f"http://cp.test/api/v1/bundles/{bundle.bundle_id}", callback=lambda _url, **_kwargs: bundle_response(bundle), repeat=True)
    holder = BundleHolder(DataPlaneMetrics())
    source = _remote_source(tmp_path, holder, http_client)
    await source.once()
    (tmp_path / "bundles.json").unlink()

    await source.once()

    assert not (tmp_path / "bundles.json").exists()


async def test_poll_revocation_updates_holder(http_mock, tmp_path, http_client):
    first = make_remote_bundle(key_ids=("k1",))
    second = make_remote_bundle(key_ids=())
    http_mock.get("http://cp.test/api/v1/bundles/manifest", callback=lambda _url, **_kwargs: manifest_response(first), repeat=False)
    http_mock.get(f"http://cp.test/api/v1/bundles/{first.bundle_id}", callback=lambda _url, **_kwargs: bundle_response(first), repeat=True)
    http_mock.get(f"http://cp.test/api/v1/bundles/{second.bundle_id}", callback=lambda _url, **_kwargs: bundle_response(second), repeat=True)
    holder = BundleHolder(DataPlaneMetrics())
    source = _remote_source(tmp_path, holder, http_client)
    await source.once()
    assert make_key("k1")[1].token_hash in holder.current.key_index

    http_mock.get("http://cp.test/api/v1/bundles/manifest", callback=lambda _url, **_kwargs: manifest_response(second), repeat=True)
    await source.once()

    assert holder.current.key_index == {}


async def test_poll_rejects_a_bundle_that_fails_schema_validation(http_mock, tmp_path, http_client):
    bundle = make_remote_bundle()
    http_mock.get("http://cp.test/api/v1/bundles/manifest", callback=lambda _url, **_kwargs: manifest_response(bundle), repeat=True)
    http_mock.get(f"http://cp.test/api/v1/bundles/{bundle.bundle_id}", status=200, payload={"data": {"schema_version": 1}}, repeat=True)
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

    assert (await healthz(request)).status_code == 200
    holder.reject_manifest()

    assert (await healthz(request)).status_code == 200


async def test_health_requires_an_accepted_configuration():
    request = Request({"type": "http"})
    request.state.runtime = SimpleNamespace(holder=BundleHolder(DataPlaneMetrics()), outbox=SimpleNamespace(accepting=True))

    response = await healthz(request)
    assert response.status_code == 503


async def test_first_empty_manifest_is_accepted_and_cached(http_mock, tmp_path, http_client):
    http_mock.get("http://cp.test/api/v1/bundles/manifest", callback=lambda _url, **_kwargs: manifest_response(), repeat=False)
    holder = BundleHolder(DataPlaneMetrics())
    source = _remote_source(tmp_path, holder, http_client)
    request = Request({"type": "http"})
    request.state.runtime = SimpleNamespace(holder=holder, outbox=SimpleNamespace(accepting=True))

    await source.once()

    assert (await healthz(request)).status_code == 200
    cached = read_cached_bundles(tmp_path)
    assert cached is not None
    assert not cached.bundles

    restarted_holder = BundleHolder(DataPlaneMetrics())
    restarted_source = _remote_source(tmp_path, restarted_holder, http_client)
    restarted_source._load_cached()
    request.state.runtime = SimpleNamespace(holder=restarted_holder, outbox=SimpleNamespace(accepting=True))
    http_mock.get("http://cp.test/api/v1/bundles/manifest", exception=TimeoutError())
    with pytest.raises(TimeoutError):
        await restarted_source.once()
    assert (await healthz(request)).status_code == 200


@pytest.mark.parametrize("populated", [False, True])
async def test_readiness_fails_when_metering_cannot_accept_work(populated):
    holder = BundleHolder(DataPlaneMetrics())
    holder.swap(BundleSet.from_bundles((make_remote_bundle(),) if populated else ()), "cached")
    request = Request({"type": "http"})
    request.state.runtime = SimpleNamespace(holder=holder, outbox=SimpleNamespace(accepting=False))

    assert (await healthz(request)).status_code == 503


async def test_poll_removes_an_org_absent_from_the_next_manifest(http_mock, tmp_path, http_client):
    other_org = uuid7()
    first = make_remote_bundle(key_ids=("first",), org=ORG)
    second = make_remote_bundle(key_ids=("second",), org=other_org)
    http_mock.get("http://cp.test/api/v1/bundles/manifest", callback=lambda _url, **_kwargs: manifest_response(first, second), repeat=False)
    http_mock.get(f"http://cp.test/api/v1/bundles/{first.bundle_id}", callback=lambda _url, **_kwargs: bundle_response(first), repeat=True)
    http_mock.get(f"http://cp.test/api/v1/bundles/{second.bundle_id}", callback=lambda _url, **_kwargs: bundle_response(second), repeat=True)
    holder = BundleHolder(DataPlaneMetrics())
    source = _remote_source(tmp_path, holder, http_client)
    await source.once()

    http_mock.get("http://cp.test/api/v1/bundles/manifest", callback=lambda _url, **_kwargs: manifest_response(first), repeat=True)
    await source.once()

    assert list(holder.current.snapshots) == [ORG]
    assert make_key("second", other_org)[1].token_hash not in holder.current.key_index
    cached = read_cached_bundles(tmp_path)
    assert cached is not None
    assert [bundle.org_id for bundle in cached.bundles] == [ORG]


async def test_poll_fetches_only_the_org_whose_bundle_changed(http_mock, tmp_path, http_client):
    other_org = uuid7()
    first = make_remote_bundle(key_ids=("first",), org=ORG)
    changed = make_remote_bundle(key_ids=("changed",), org=ORG)
    second = make_remote_bundle(key_ids=("second",), org=other_org)
    http_mock.get("http://cp.test/api/v1/bundles/manifest", callback=lambda _url, **_kwargs: manifest_response(first, second), repeat=False)
    http_mock.get(f"http://cp.test/api/v1/bundles/{first.bundle_id}", callback=lambda _url, **_kwargs: bundle_response(first), repeat=True)
    http_mock.get(f"http://cp.test/api/v1/bundles/{changed.bundle_id}", callback=lambda _url, **_kwargs: bundle_response(changed), repeat=True)
    http_mock.get(f"http://cp.test/api/v1/bundles/{second.bundle_id}", callback=lambda _url, **_kwargs: bundle_response(second), repeat=True)
    holder = BundleHolder(DataPlaneMetrics())
    source = _remote_source(tmp_path, holder, http_client)
    await source.once()

    http_mock.get("http://cp.test/api/v1/bundles/manifest", callback=lambda _url, **_kwargs: manifest_response(changed, second), repeat=True)
    await source.once()

    assert len(http_mock.requests.get(("GET", URL(f"http://cp.test/api/v1/bundles/{first.bundle_id}")), [])) == 1
    assert len(http_mock.requests.get(("GET", URL(f"http://cp.test/api/v1/bundles/{changed.bundle_id}")), [])) == 1
    assert len(http_mock.requests.get(("GET", URL(f"http://cp.test/api/v1/bundles/{second.bundle_id}")), [])) == 1
    assert make_key("changed", ORG)[1].token_hash in holder.current.key_index
    assert make_key("second", other_org)[1].token_hash in holder.current.key_index


async def test_poll_rejects_a_bundle_that_does_not_match_its_manifest_entry(http_mock, tmp_path, http_client):
    expected = make_remote_bundle(key_ids=("expected",))
    mismatched = make_remote_bundle(key_ids=("mismatched",))
    http_mock.get("http://cp.test/api/v1/bundles/manifest", callback=lambda _url, **_kwargs: manifest_response(expected), repeat=True)
    http_mock.get(f"http://cp.test/api/v1/bundles/{expected.bundle_id}", callback=lambda _url, **_kwargs: bundle_response(mismatched), repeat=True)
    holder = BundleHolder(DataPlaneMetrics())

    with pytest.raises(ValueError, match="does not match manifest entry"):
        await _remote_source(tmp_path, holder, http_client).once()

    assert holder.current.snapshots == {}
    assert read_cached_bundles(tmp_path) is None


async def test_poll_rejects_a_token_hash_shared_by_two_org_bundles(http_mock, tmp_path, http_client):
    other_org = uuid7()
    first = make_remote_bundle(key_ids=("same",), org=ORG)
    second = make_remote_bundle(key_ids=("same",), org=other_org)
    http_mock.get("http://cp.test/api/v1/bundles/manifest", callback=lambda _url, **_kwargs: manifest_response(first, second), repeat=True)
    http_mock.get(f"http://cp.test/api/v1/bundles/{first.bundle_id}", callback=lambda _url, **_kwargs: bundle_response(first), repeat=True)
    http_mock.get(f"http://cp.test/api/v1/bundles/{second.bundle_id}", callback=lambda _url, **_kwargs: bundle_response(second), repeat=True)
    holder = BundleHolder(DataPlaneMetrics())

    with pytest.raises(ValueError, match="token hash appears in more than one bundle"):
        await _remote_source(tmp_path, holder, http_client).once()

    assert holder.current.snapshots == {}
    assert read_cached_bundles(tmp_path) is None
