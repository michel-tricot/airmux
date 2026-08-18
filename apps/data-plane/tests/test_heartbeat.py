from __future__ import annotations

import json

import httpx
import respx
from conftest import make_bundle

from contract import uuid7
from data_plane.bundle import BundleHolder
from data_plane.control_plane_link import ControlPlaneLink
from data_plane.heartbeat import Heartbeat


@respx.mock
async def test_heartbeat_owns_transport_and_reports_the_current_bundle(http_client):
    holder = BundleHolder()
    bundle = make_bundle()
    holder.admit(bundle, source="test")
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
