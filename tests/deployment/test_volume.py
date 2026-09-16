from __future__ import annotations

import os
import subprocess
import time
import uuid

import pytest
from test_docker import docker


def test_empty_cloud_volume_is_writable_by_unprivileged_services():
    image = os.environ.get("DEPLOYMENT_IMAGE")
    if image is None:
        pytest.skip("set DEPLOYMENT_IMAGE to the built airmux image")
    volume = f"airmux-volume-test-{uuid.uuid4().hex}"
    docker("volume", "create", volume)
    try:
        with pytest.raises(subprocess.CalledProcessError):
            docker(
                "run",
                "--rm",
                "--mount",
                f"type=volume,src={volume},dst=/state,volume-nocopy",
                "--env",
                "DATABASE_URL=postgresql+asyncpg://airmux:airmux@127.0.0.1:1/airmux",
                image,
                "all-in-one",
            )
        output = docker(
            "run",
            "--rm",
            "--user",
            "10001:10001",
            "--entrypoint",
            "sh",
            "--mount",
            f"type=volume,src={volume},dst=/state,volume-nocopy",
            image,
            "-ec",
            "test $(id -u) = 10001; touch /state/runtime/key /state/secrets/key /state/data-plane/outbox; echo writable",
        )
        assert output == "writable"
        with pytest.raises(subprocess.CalledProcessError) as result:
            docker("run", "--rm", "--entrypoint", "sh", image, "-c", "exit 23")
        assert result.value.returncode == 23
    finally:
        docker("volume", "rm", volume)


def test_console_accepts_flys_ipv6_resolver():
    image = os.environ.get("DEPLOYMENT_IMAGE")
    if image is None:
        pytest.skip("set DEPLOYMENT_IMAGE to the built airmux image")
    container = docker(
        "run",
        "--detach",
        "--rm",
        "--env",
        "NGINX_RESOLVER=fdaa::3",
        "--env",
        "AIRMUX_CONSOLE_URL=https://airmux.example.com",
        image,
        "console",
    )
    try:
        time.sleep(1)
        assert docker("inspect", "--format", "{{.State.Running}}", container) == "true"
    finally:
        docker("rm", "-f", container)


def test_image_defaults_to_all_in_one_and_rejects_unknown_roles():
    image = os.environ.get("DEPLOYMENT_IMAGE")
    if image is None:
        pytest.skip("set DEPLOYMENT_IMAGE to the built airmux image")
    assert docker("inspect", "--format", "{{json .Config.Cmd}}", image) == '["all-in-one"]'
    result = subprocess.run(["docker", "run", "--rm", image, "unknown"], capture_output=True, text=True, check=False)  # noqa: S603,S607 controlled Docker test command
    assert result.returncode == 2
    assert "Expected all-in-one, console, control-plane, data-plane, or setup" in result.stderr
