from __future__ import annotations

import json
import threading
from copy import deepcopy
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING
from uuid import UUID

import httpx
import pytest
import yaml
from gateway_harness import INFERENCE_KEY, eventually

from contract import token_hash, uuid7

if TYPE_CHECKING:
    from pathlib import Path

    from gateway_harness import Gateway


@pytest.fixture
def bundle_server(tmp_path):
    directory = tmp_path / "control-plane"
    (directory / "api/v1/bundles").mkdir(parents=True)
    with ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(directory))) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield directory, f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            thread.join(timeout=5)


def publish(directory: Path, bundle: dict):
    bundles = directory / "api/v1/bundles"
    (bundles / bundle["bundle_id"]).write_text(json.dumps({"data": bundle}))
    manifest = {"data": {"bundles": [{"org_id": bundle["org_id"], "bundle_id": bundle["bundle_id"]}]}}
    replacement = bundles / "manifest.new"
    replacement.write_text(json.dumps(manifest))
    replacement.replace(bundles / "manifest")


def remote_bundle(gateway: Gateway):
    org = str(UUID(int=0))
    return {
        "schema_version": 1,
        "bundle_id": str(uuid7()),
        "org_id": org,
        "issued_at": "2026-09-18T00:00:00Z",
        "keys": [
            {
                "key_id": "remote",
                "org_id": org,
                "workspace_id": org,
                "user_id": str(uuid7()),
                "token_hash": token_hash(INFERENCE_KEY),
                "request_source": "inference_key",
                "expires_at": "2999-01-01T00:00:00Z",
            }
        ],
        "catalog": {
            **deepcopy(gateway.taxonomy),
            "credentials": [
                {"ref": {"purpose": "provider", "service": "stub", "name": "default", "secret_id": str(uuid7())}, "priority": 100, "version": 1}
            ],
        },
        "policies": [],
    }


@pytest.mark.parametrize("invalid", ["context_window", "max_output_tokens", "unknown", "expires_at", "issued_at"])
def test_remote_reload_rejects_invalid_bundle_and_keeps_serving(gateway: Gateway, bundle_server, invalid: str):
    gateway.add_provider()
    directory, url = bundle_server
    original = remote_bundle(gateway)
    publish(directory, original)
    gateway.write_files()
    config = yaml.safe_load(gateway.config_path.read_text())
    config["data_plane"]["bundle"] = {
        "kind": "remote",
        "control_plane": {"url": url, "management_key": "test-management"},
        "cache_dir": "cache",
        "poll_interval_s": 0.05,
    }
    gateway.config_path.write_text(yaml.safe_dump(config))
    gateway.launch()
    eventually(gateway.ready)
    assert gateway.request().status_code == 200
    cache_path = gateway.directory / "cache/bundles.json"
    original_cache = cache_path.read_bytes()
    invalid_bundle = deepcopy(original)
    invalid_bundle["bundle_id"] = str(uuid7())
    if invalid in ("context_window", "max_output_tokens"):
        invalid_bundle["catalog"]["models"][0][invalid] = -1
    elif invalid == "expires_at":
        invalid_bundle["keys"][0][invalid] = "2999-01-01T00:00:00"
    elif invalid == "issued_at":
        invalid_bundle[invalid] = "2026-09-18T00:00:00"
    else:
        invalid_bundle["catalog"]["models"][0][invalid] = True
    publish(directory, invalid_bundle)
    eventually(lambda: "bundle_manifest_rejected" in (gateway.directory / "gateway.log").read_text())
    assert gateway.ready()
    assert gateway.request().status_code == 200
    assert cache_path.read_bytes() == original_cache
    assert all(str(event.bundle_id) == original["bundle_id"] for event in gateway.events(2))
    replacement = deepcopy(original)
    replacement["bundle_id"] = str(uuid7())
    replacement["keys"][0]["token_hash"] = token_hash("sk-inf-replacement")
    publish(directory, replacement)
    eventually(lambda: json.loads(cache_path.read_text())["bundles"][0]["bundle_id"] == replacement["bundle_id"])
    assert gateway.request(key="sk-inf-replacement").status_code == 200
    assert gateway.request().status_code == 401
    assert str(gateway.events(3)[-1].bundle_id) == replacement["bundle_id"]
    assert httpx.get(f"{gateway.url}/readyz").status_code == 200
