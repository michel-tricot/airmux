from __future__ import annotations

from conftest import make_bundle
from yarl import URL

from contract import uuid7
from data_plane.bundle import BundleHolder
from data_plane.bundle.holder import BundleSet
from data_plane.control_plane_link import ControlPlaneLink
from data_plane.heartbeat import Heartbeat
from data_plane.metrics import DataPlaneMetrics


async def test_heartbeat_reports_a_bundle_only_when_the_manifest_contains_one(http_mock, http_client):
    holder = BundleHolder(DataPlaneMetrics())
    bundle = make_bundle()
    holder.swap(BundleSet.from_bundles((bundle,)), source="test")
    instance_id = uuid7()
    http_mock.post("http://cp.test/api/v1/heartbeat", status=200, repeat=True)
    heartbeat = Heartbeat(
        control_plane=ControlPlaneLink(url="http://cp.test", management_key="dp-token"),
        interval_s=30,
        holder=holder,
        instance_id=instance_id,
        http_client=http_client,
    )

    await heartbeat.once()

    sent = http_mock.requests.get(("POST", URL("http://cp.test/api/v1/heartbeat")), [])[-1].kwargs["json"]
    assert sent["instance_id"] == str(instance_id)
    assert sent["bundle_id"] == str(bundle.bundle_id)
    assert http_mock.requests.get(("POST", URL("http://cp.test/api/v1/heartbeat")), [])[-1].kwargs["headers"]["authorization"] == "Bearer dp-token"

    holder.swap(BundleSet.from_bundles((bundle, make_bundle().model_copy(update={"org_id": uuid7()}))), source="test")
    await heartbeat.once()
    sent = http_mock.requests.get(("POST", URL("http://cp.test/api/v1/heartbeat")), [])[-1].kwargs["json"]
    assert sent["bundle_id"] is None
