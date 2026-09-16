from __future__ import annotations

from typing import TYPE_CHECKING

import yaml
from gateway_harness import eventually
from upstream import TEXT, UPSTREAM_KEY

if TYPE_CHECKING:
    from gateway_harness import Gateway


def test_embedded_taxonomy_serves_with_a_minimal_environment(gateway: Gateway) -> None:
    provider = gateway.add_provider()
    gateway.bundle_path.write_text(yaml.safe_dump({"keys": gateway.bundle["keys"], "taxonomy": gateway.taxonomy}))
    gateway.config_path.write_text(
        yaml.safe_dump({"data_plane": {"bundle": {"kind": "local", "path": str(gateway.bundle_path)}, "events": {"kind": "devnull"}}})
    )
    gateway.environment = {"PATH": "/usr/bin:/bin", "STUB_API_KEY": UPSTREAM_KEY, "HOME": str(gateway.directory)}
    gateway.launch()
    eventually(gateway.ready)
    response = gateway.request()
    assert response.status_code == 200, response.text
    assert response.json()["content"] == [{"type": "text", "text": TEXT}]
    assert [request.headers["authorization"] for request in provider.requests] == [f"Bearer {UPSTREAM_KEY}"]
