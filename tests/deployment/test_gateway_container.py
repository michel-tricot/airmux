from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import yaml
from test_docker import ROOT, assert_completion, docker, eventually


def test_gateway_container_serves_a_native_configuration_without_a_control_plane(tmp_path):
    image = os.environ.get("DEPLOYMENT_GATEWAY_IMAGE")
    if image is None:
        pytest.skip("set DEPLOYMENT_GATEWAY_IMAGE to the built data-plane target")
    network = f"tokkeeper-standalone-{uuid4().hex[:12]}"
    upstream = f"{network}-upstream"
    gateway = f"{network}-gateway"
    taxonomy = tmp_path / "taxonomy.yml"
    taxonomy.write_text(
        yaml.safe_dump(
            {
                "providers": [{"provider_id": "deployment", "base_url": "http://upstream:9000"}],
                "models": [{"model_id": "echo", "provider_id": "deployment", "input_modalities": ["text"], "output_modalities": ["text"]}],
            }
        )
    )
    subprocess.run(  # noqa: S603 the test environment supplies the installed project CLI
        [str(Path(sys.executable).parent / "tokkeeper"), "gateway", "init", "--taxonomy", str(taxonomy), "--directory", str(tmp_path / "gateway")],
        check=True,
        capture_output=True,
    )
    key = (tmp_path / "gateway/inference.key").read_text().strip()
    docker("network", "create", network)
    try:
        docker(
            "run",
            "-d",
            "--name",
            upstream,
            "--network",
            network,
            "--network-alias",
            "upstream",
            "--mount",
            f"type=bind,source={ROOT / 'tests/deployment/upstream.py'},target=/upstream.py,readonly",
            "--entrypoint",
            "python",
            image,
            "/upstream.py",
        )
        docker(
            "run",
            "-d",
            "--name",
            gateway,
            "--network",
            network,
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--mount",
            f"type=bind,source={tmp_path},target=/config,readonly",
            "-e",
            "DEPLOYMENT_API_KEY=deployment-test-key",
            "-p",
            "127.0.0.1::8081",
            image,
            "serve",
            "--config",
            "/config/gateway/tokkeeper.yml",
            "--host",
            "0.0.0.0",  # noqa: S104 listen on the container interface behind a loopback-only published port
            "--port",
            "8081",
        )
        address = docker("port", gateway, "8081/tcp")
        with httpx.Client(base_url=f"http://{address}", timeout=5) as client:
            eventually(lambda: client.get("/readyz").status_code == 200)
            body = {"model": "echo", "messages": [{"role": "user", "content": "hello"}]}
            headers = {"Authorization": f"Bearer {key}", "X-Tokkeeper-Dialect": "openai_native"}
            assert client.post("/inf/v1/chat/completions", json=body).status_code == 401
            response = client.post("/inf/v1/chat/completions", headers=headers, json=body)
            assert_completion(response)
            with client.stream("POST", "/inf/v1/chat/completions", headers=headers, json={**body, "stream": True}) as stream:
                assert stream.status_code == 200
                assert "data: [DONE]" in list(stream.iter_lines())
    finally:
        docker("rm", "-f", gateway, upstream)
        docker("network", "rm", network)
