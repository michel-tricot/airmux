from __future__ import annotations

import os
import subprocess
import time
import uuid

import pytest
from test_docker import docker


def test_empty_cloud_volume_is_writable_by_unprivileged_services():
    image = os.environ.get("DEPLOYMENT_COMPACT_IMAGE")
    if image is None:
        pytest.skip("set DEPLOYMENT_COMPACT_IMAGE to a built all-in-one image")
    volume = f"tokkeeper-volume-test-{uuid.uuid4().hex}"
    docker("volume", "create", volume)
    try:
        output = docker(
            "run",
            "--rm",
            "--mount",
            f"type=volume,src={volume},dst=/state,volume-nocopy",
            image,
            "sh",
            "-ec",
            "test $(id -u) = 10001; touch /state/runtime/key /state/secrets/key /state/data-plane/outbox; echo writable",
        )
        assert output == "writable"
        with pytest.raises(subprocess.CalledProcessError) as result:
            docker("run", "--rm", image, "sh", "-c", "exit 23")
        assert result.value.returncode == 23
    finally:
        docker("volume", "rm", volume)


def test_console_accepts_flys_ipv6_resolver():
    image = os.environ.get("DEPLOYMENT_COMPACT_IMAGE")
    if image is None:
        pytest.skip("set DEPLOYMENT_COMPACT_IMAGE to a built all-in-one image")
    container = docker(
        "run",
        "--detach",
        "--rm",
        "--env",
        "NGINX_RESOLVER=fdaa::3",
        "--env",
        "TOKKEEPER_CONSOLE_URL=https://tokkeeper.example.com",
        "--entrypoint",
        "/app/deploy/docker/start.sh",
        image,
        "console",
    )
    try:
        time.sleep(1)
        assert docker("inspect", "--format", "{{.State.Running}}", container) == "true"
    finally:
        docker("rm", "-f", container)
