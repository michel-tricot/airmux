from __future__ import annotations

import json

import httpx
import respx
from conftest import make_bundle

from contract import uuid7
from data_plane.bundle import BundleHolder
from data_plane.bundle.holder import BundleSet
from data_plane.control_plane_link import ControlPlaneLink
from data_plane.heartbeat import Heartbeat


@respx.mock
async def test_heartbeat_reports_a_bundle_only_when_the_manifest_contains_one(http_client):
    holder = BundleHolder()
    bundle = make_bundle()
    holder.swap(BundleSet.from_bundles((bundle,)), source="test")
    instance_id = uuid7()
    route = respx.post("http://cp.test/api/v1/heartbeat").mock(return_value=httpx.Response(200))
    heartbeat = Heartbeat(
        control_plane=ControlPlaneLink(url="http://cp.test", token="dp-token"),
        interval_s=30,
        holder=holder,
        instance_id=instance_id,
        http_client=http_client,
    )

    await heartbeat.once()

    sent = json.loads(route.calls.last.request.content)
    assert sent["instance_id"] == str(instance_id)
    assert sent["bundle_id"] == str(bundle.bundle_id)
    assert route.calls.last.request.headers["authorization"] == "Bearer dp-token"

    holder.swap(BundleSet.from_bundles((bundle, make_bundle().model_copy(update={"org_id": uuid7()}))), source="test")
    await heartbeat.once()
    sent = json.loads(route.calls.last.request.content)
    assert sent["bundle_id"] is None
