from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import yaml
from test_docker import ROOT, assert_completion, docker, eventually


def test_documented_gateway_container_serves_from_a_fresh_configuration_directory(tmp_path):
    image = os.environ.get("DEPLOYMENT_IMAGE")
    if image is None:
        pytest.skip("set DEPLOYMENT_IMAGE to the built airmux image")
    network = f"airmux-standalone-{uuid4().hex[:12]}"
    upstream = f"{network}-upstream"
    gateway = f"{network}-gateway"
    directory = tmp_path / "gateway config"
    directory.mkdir()
    subprocess.run(  # noqa: S603 the test environment supplies the installed project CLI
        [str(Path(sys.executable).parent / "airmux"), "gateway", "init"],
        cwd=directory,
        check=True,
        capture_output=True,
    )
    taxonomy = directory / ".airmux/taxonomy.yml"
    taxonomy.write_text(
        yaml.safe_dump(
            {
                "providers": [{"provider_id": "openai", "base_url": "http://upstream:9000"}],
                "models": [{"model_id": "openai/gpt-5.4-mini", "provider_id": "openai", "input_modalities": ["text"], "output_modalities": ["text"]}],
            }
        )
    )
    inference_key = directory / ".airmux/inference.key"
    assert stat.S_IMODE(inference_key.stat().st_mode) == 0o600
    key = inference_key.read_text().strip()
    guide = (ROOT / "docs/deployment/gateway.mdx").read_text()
    recipe = next(block for block in re.findall(r"```bash\n(.*?)```", guide, re.DOTALL) if "docker run" in block)
    command = (
        recipe.replace("docker run", f"docker run -d --name {gateway} --network {network}")
        .replace("-p 127.0.0.1:8080:8081", "-p 127.0.0.1::8081")
        .replace("airmux:local", image)
    )
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
        result = subprocess.run(  # noqa: S603 execute the repository's documented shell recipe
            ["/bin/bash", "-e", "-c", command],
            cwd=directory,
            env={**os.environ, "AIRMUX_CONFIG_DIR": str(directory), "OPENAI_API_KEY": "deployment-test-key"},
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        address = docker("port", gateway, "8081/tcp")
        with httpx.Client(base_url=f"http://{address}", timeout=5) as client:
            eventually(lambda: client.get("/healthz").status_code == 200)
            body = {"model": "openai/gpt-5.4-mini", "messages": [{"role": "user", "content": "hello"}]}
            headers = {"Authorization": f"Bearer {key}"}
            assert client.post("/inf/v1/chat/completions", json=body).status_code == 401
            response = client.post("/inf/v1/chat/completions", headers=headers, json=body)
            assert_completion(response)
            with client.stream("POST", "/inf/v1/chat/completions", headers=headers, json={**body, "stream": True}) as stream:
                assert stream.status_code == 200
                assert "data: [DONE]" in list(stream.iter_lines())
    finally:
        docker("rm", "-f", gateway, upstream)
        docker("network", "rm", network)
