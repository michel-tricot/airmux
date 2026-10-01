from __future__ import annotations

import os
import subprocess
import uuid
from urllib.parse import urlsplit

import httpx
import pytest
from test_docker import docker, eventually


def test_named_volume_is_writable_by_default_user():
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
                f"type=volume,src={volume},dst=/state",
                "--env",
                "DATABASE_URL=postgresql+asyncpg://airmux:airmux@127.0.0.1:1/airmux",
                image,
                "airmux",
            )
        output = docker(
            "run",
            "--rm",
            "--user",
            "10001:10001",
            "--entrypoint",
            "sh",
            "--mount",
            f"type=volume,src={volume},dst=/state",
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


@pytest.mark.parametrize("user", [None, "0:0"])
def test_console_accepts_flys_ipv6_resolver(user):
    image = os.environ.get("DEPLOYMENT_IMAGE")
    if image is None:
        pytest.skip("set DEPLOYMENT_IMAGE to the built airmux image")
    user_args = () if user is None else ("--user", user)
    container = docker(
        "run",
        "--detach",
        "--rm",
        "--publish",
        "127.0.0.1::8080",
        *user_args,
        "--env",
        "NGINX_RESOLVER=fdaa::3",
        "--env",
        "AIRMUX_CONSOLE_URL=https://airmux.example.com",
        image,
        "console",
    )
    try:
        address = docker("port", container, "8080/tcp")
        with httpx.Client(base_url=f"http://{address}", timeout=2) as client:
            eventually(lambda: client.get("/", headers={"Host": "airmux.example.com"}).status_code == 200)
    finally:
        docker("rm", "-f", container)


def test_image_defaults_to_airmux_and_rejects_unknown_roles():
    image = os.environ.get("DEPLOYMENT_IMAGE")
    if image is None:
        pytest.skip("set DEPLOYMENT_IMAGE to the built airmux image")
    assert docker("inspect", "--format", "{{json .Config.Cmd}}", image) == '["airmux"]'
    assert docker("inspect", "--format", "{{json .Config.User}}", image) == '"10001:10001"'
    for user in (None, "0:0"):
        user_args = () if user is None else ("--user", user)
        result = subprocess.run(  # noqa: S603 controlled Docker test command
            ["docker", "run", "--rm", *user_args, image, "unknown"],  # noqa: S607 controlled Docker executable
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 2
        assert "Expected airmux, console, control-plane, data-plane, migrate, or taxonomy" in result.stderr.splitlines()


@pytest.mark.parametrize("console_url", ["https://console.example.test", "http://localhost:8080", "http://[::1]:8080"])
def test_console_is_only_served_on_its_configured_hostname(console_url):
    image = os.environ.get("DEPLOYMENT_IMAGE")
    if image is None:
        pytest.skip("set DEPLOYMENT_IMAGE to the built airmux image")
    container = docker("run", "--detach", "--rm", "--publish", "127.0.0.1::8080", "--env", f"AIRMUX_CONSOLE_URL={console_url}", image, "console")
    try:
        address = docker("port", container, "8080/tcp")
        console_host = urlsplit(console_url).netloc
        with httpx.Client(base_url=f"http://{address}", timeout=2) as client:
            eventually(lambda: client.get("/", headers={"Host": console_host}).status_code == 200)
            for host in (console_host, console_host.upper()):
                assert "<!doctype html>" in client.get("/org", headers={"Host": host}).text.lower()
            for host in ("api.example.test", "other.example.test"):
                for path in ("/", "/org", "/index.html", "/assets/index.js", "/metrics"):
                    response = client.get(path, headers={"Host": host, "X-Forwarded-Host": console_host})
                    assert response.status_code == 404, (host, path, response.text)
                    assert "<!doctype html>" not in response.text.lower()
    finally:
        docker("rm", "-f", container)
