from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]


def docker(*args):
    return subprocess.run(["docker", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()  # noqa: S603,S607 controlled Docker test commands


def payload(response):
    assert response.is_success, response.text
    return response.json()["data"]


def assert_completion(response):
    assert response.status_code == 200, response.text
    assert response.json()["choices"][0]["message"]["content"] == "deployment ready", response.text


def eventually(check, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    assert check()


@pytest.fixture
def deployment():
    project = os.environ.get("DEPLOYMENT_PROJECT")
    if project is None:
        pytest.skip("start a fresh deployment and set DEPLOYMENT_PROJECT, DEPLOYMENT_FILE, and DEPLOYMENT_URL")
    compose_file = os.environ["DEPLOYMENT_FILE"]
    url = os.environ["DEPLOYMENT_URL"]
    compose = ("compose", "-p", project, "-f", compose_file)
    compact = compose_file == "docker-compose.yml"
    gateways = ("cli",) if compact else ("data-plane-1", "data-plane-2")
    gateway = gateways[0]
    container = docker(*compose, "ps", "-q", gateway)
    image = docker("inspect", "--format", "{{.Config.Image}}", container)
    upstream = f"{project}-upstream"
    docker(
        "run",
        "-d",
        "--rm",
        "--name",
        upstream,
        "--network",
        f"{project}_default",
        "--network-alias",
        "deployment-upstream",
        "-v",
        f"{ROOT / 'tests/deployment/upstream.py'}:/upstream.py:ro",
        "--entrypoint",
        "python",
        image,
        "/upstream.py",
    )
    try:
        with httpx.Client(base_url=url, headers={"X-Requested-With": "XMLHttpRequest"}, timeout=10) as client:
            eventually(lambda: client.get("/healthz").status_code == 503)
            yield client, compose, gateways, compact
    finally:
        try:
            artifacts = os.environ.get("AIRMUX_DEPLOYMENT_ARTIFACTS")
            if artifacts:
                destination = Path(artifacts)
                destination.mkdir(parents=True, exist_ok=True)
                output = subprocess.run(["docker", "logs", upstream], cwd=ROOT, capture_output=True, text=True, check=True)  # noqa: S603,S607 controlled Docker test command
                contents = (output.stdout + output.stderr).replace("deployment-test-key", "[REDACTED]").replace("deployment-password", "[REDACTED]")
                (destination / "upstream.log").write_text(contents, encoding="utf-8")
        finally:
            docker("rm", "-f", upstream)


def service_action(compose, action, service):
    container = docker(*compose, "ps", "--all", "--quiet", service)
    docker(action, container)


def assert_unprivileged(compose, service, expected):
    container = docker(*compose, "ps", "-q", service)
    processes = docker("top", container, "-eo", "pid,user,args")
    servers = [
        process
        for process in processes.splitlines()[1:]
        if not process.split()[2].endswith("/docker-init") and any(name in process for name in ("airmux control-plane", "airmux gateway", "nginx:"))
    ]
    assert servers
    assert all(server.split()[1] in {"airmux", "10001"} for server in servers), processes
    assert all(sum(command in server for server in servers) == 1 for command in expected), processes


def assert_process_layout(client, compose, gateways, compact):
    assert_installed_packages(compose, gateways[0])
    lifecycle = ("migrate", "taxonomy")
    services = (*lifecycle, "cli") if compact else (*lifecycle, "control-plane", *gateways, "console")
    containers = [docker(*compose, "ps", "--all", "--quiet", service) for service in services]
    assert len({docker("inspect", "--format", "{{.Image}}", container) for container in containers}) == 1
    for service in lifecycle:
        container = docker(*compose, "ps", "--all", "--quiet", service)
        assert docker("inspect", "--format", "{{.State.Status}} {{.State.ExitCode}}", container) == "exited 0"
    if compact:
        assert_unprivileged(compose, gateways[0], ("airmux control-plane serve", "airmux gateway serve", "nginx: master"))
    else:
        assert_unprivileged(compose, "control-plane", ("airmux control-plane serve",))
        for gateway in gateways:
            assert_unprivileged(compose, gateway, ("airmux gateway serve",))
        assert_unprivileged(compose, "console", ("nginx: master",))
    body = client.get("/metrics").text
    assert "airmux_control_plane_" not in body
    assert "airmux_data_plane_" not in body


def assert_quickstart(public_url, config_path):
    uv = shutil.which("uv")
    assert uv is not None
    output = subprocess.run(  # noqa: S603 controlled project CLI test command
        [
            uv,
            "run",
            "--package",
            "airmux",
            "--no-dev",
            "--no-sync",
            "airmux",
            "quickstart",
            "--url",
            public_url,
            "--email",
            "owner@deployment.test",
            "--password",
            "deployment-password",
        ],
        cwd=ROOT,
        env={**os.environ, "AIRMUX_CLI_CONFIG": str(config_path), "DEPLOYMENT_API_KEY": "deployment-test-key"},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "Ready." in output
    assert "DEPLOYMENT_API_KEY" in output
    assert f"curl {public_url}/inf/v1/chat/completions" in output


def assert_installed_packages(compose, gateway):
    container = docker(*compose, "ps", "-q", gateway)
    assert docker("exec", container, "airmux", "--version").startswith("airmux ")
    assert "--config" in docker("exec", container, "airmux", "gateway", "serve", "--help")
    assert "--config" in docker("exec", container, "airmux", "control-plane", "serve", "--help")


def assert_control_plane_outage(client, compose, path, headers, request):
    service_action(compose, "stop", "control-plane")
    eventually(lambda: client.get("/healthz").status_code == 503)
    gateway = docker(*compose, "ps", "-q", "data-plane-1")
    assert '"status":"ready"' in docker(
        "exec", gateway, "python", "-c", "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8081/healthz').read().decode())"
    )
    assert all(client.post(path, headers=headers, json=request).status_code == 200 for _ in range(10))


def test_onboarding_inference_streaming_and_persistence(deployment, tmp_path):
    client, compose, gateways, compact = deployment
    gateway = gateways[0]
    provider = "deployment"
    assert payload(client.get("/api/v1/instance/oss/claim")) == {"claimed": False, "public_signup": False}
    assert "<!doctype html>" in client.get("/org").text.lower()
    owner = payload(client.post("/api/v1/auth/signup", json={"email": "owner@deployment.test", "name": "Owner", "password": "deployment-password"}))
    assert owner["instance_role"] == "owner"
    org = payload(client.post("/api/v1/enroll/org", json={"name": "Deployment"}))
    base = f"/api/v1/organizations/{org['id']}"
    workspace = payload(client.post(f"{base}/workspaces", json={"name": "default"}))
    key = payload(
        client.post(
            f"{base}/workspaces/{workspace['id']}/inference-keys",
            json={"label": "deployment", "user_id": owner["user_id"]},
        )
    )
    payload(client.post("/api/v1/instance/taxonomy/providers", json={"provider_id": provider, "base_url": "http://deployment-upstream:9000"}))
    payload(
        client.post(
            "/api/v1/instance/taxonomy/models",
            json={"model_id": "deployment-echo", "provider_id": provider, "input_modalities": ["text"], "output_modalities": ["text"]},
        )
    )
    payload(client.post(f"{base}/provider-credentials", json={"provider": provider, "value": "deployment-test-key"}))
    headers = {"Authorization": f"Bearer {key['token']}"}
    request = {"model": "deployment-echo", "messages": [{"role": "user", "content": "hello"}]}
    path = "/inf/v1/chat/completions"
    eventually(lambda: all(client.post(path, headers=headers, json=request).status_code == 200 for _ in range(10)))
    response = client.post(path, headers=headers, json=request)
    assert_completion(response)
    started = time.monotonic()
    with client.stream("POST", path, headers=headers, json={**request, "stream": True}) as response:
        assert response.status_code == 200
        lines = response.iter_lines()
        first = next(line for line in lines if line.startswith("data: ") and "deployment ready" in line)
        assert time.monotonic() - started < 1.5
        assert "deployment ready" in first
        assert "data: [DONE]" in list(lines)
    eventually(lambda: len(payload(client.get(f"{base}/events"))) >= 3)
    eventually(lambda: len(payload(client.get("/api/v1/instance/data-planes"))) == len(gateways))
    instance_ids = {instance["instance_id"] for instance in payload(client.get("/api/v1/instance/data-planes"))}
    assert len(instance_ids) == len(gateways)
    assert_process_layout(client, compose, gateways, compact)

    assert_quickstart(str(client.base_url).rstrip("/"), tmp_path / "cli.toml")
    if len(gateways) == 2:
        service_action(compose, "stop", gateways[1])
    if not compact:
        assert_control_plane_outage(client, compose, path, headers, request)
    service_action(compose, "restart", gateway)
    eventually(lambda: client.post(path, headers=headers, json=request).status_code == 200)
    if not compact:
        service_action(compose, "start", "control-plane")
    if len(gateways) == 2:
        service_action(compose, "start", gateways[1])
    eventually(lambda: client.get("/healthz").status_code == 200)
    eventually(lambda: client.get("/api/v1/instance/oss/claim").status_code == 200)
    assert payload(client.get("/api/v1/instance/oss/claim")) == {"claimed": True, "public_signup": False}
    eventually(lambda: {instance["instance_id"] for instance in payload(client.get("/api/v1/instance/data-planes"))} == instance_ids)
    eventually(lambda: len(payload(client.get(f"{base}/events"))) >= (4 if compact else 5))
    eventually(lambda: all(client.post(path, headers=headers, json=request).status_code == 200 for _ in range(10)))
