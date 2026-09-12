from __future__ import annotations

import json
import os
import shutil
import ssl
import subprocess
import uuid
from http.cookies import SimpleCookie

import httpx
import pytest
from test_docker import ROOT, docker, eventually, payload


@pytest.fixture(scope="module")
def https_deployment(tmp_path_factory):
    if "DEPLOYMENT_PROJECT" not in os.environ:
        pytest.skip("set DEPLOYMENT_PROJECT and DEPLOYMENT_FILE to test built deployment images")
    directory = tmp_path_factory.mktemp("https-proxy")
    project = f"airllm-https-{uuid.uuid4().hex[:10]}"
    compose_file = os.environ["DEPLOYMENT_FILE"]
    compact = compose_file == "docker-compose.yml"
    gateway = "airllm" if compact else "console"
    control_plane = "airllm" if compact else "control-plane"
    compose = ("compose", "-p", project, "-f", compose_file)
    environment = {**os.environ, "AIRLLM_PORT": "127.0.0.1:0", "AIRLLM_PUBLIC_URL": "https://localhost"}
    certificate = directory / "certificate.pem"
    private_key = directory / "key.pem"
    openssl = shutil.which("openssl")
    docker_binary = shutil.which("docker")
    assert openssl is not None
    assert docker_binary is not None
    subprocess.run(  # noqa: S603 fixed OpenSSL arguments create a disposable local test certificate
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(private_key),
            "-out",
            str(certificate),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
        ],
        check=True,
        capture_output=True,
    )
    caddyfile = directory / "Caddyfile"
    caddyfile.write_text(f"https://localhost {{\n tls /test/certificate.pem /test/key.pem\n reverse_proxy {gateway}:8080\n}}\n")
    edge = f"{project}-tls"
    upstream = f"{project}-upstream"
    started = False
    upstream_started = False
    try:
        subprocess.run(  # noqa: S603 isolated Compose project uses the repository deployment configuration
            [docker_binary, *compose, "up", "--detach", "--no-build", "--wait", "--wait-timeout", "180"],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        docker(
            "run",
            "--detach",
            "--name",
            edge,
            "--network",
            f"{project}_default",
            "--publish",
            "127.0.0.1::443",
            "--volume",
            f"{directory}:/test:ro",
            "caddy:2",
            "caddy",
            "run",
            "--config",
            "/test/Caddyfile",
            "--adapter",
            "caddyfile",
        )
        started = True
        port = docker("port", edge, "443/tcp").rsplit(":", 1)[1]
        proxy = docker(*compose, "ps", "-q", gateway)
        direct = "http://" + docker("port", proxy, "8080/tcp")
        backend = docker(*compose, "ps", "-q", control_plane)
        image = docker("inspect", "--format", "{{.Config.Image}}", backend)
        docker(
            "run",
            "--detach",
            "--name",
            upstream,
            "--network",
            f"{project}_default",
            "--network-alias",
            "deployment-upstream",
            "--volume",
            f"{ROOT / 'tests/deployment/upstream.py'}:/upstream.py:ro",
            "--entrypoint",
            "python",
            image,
            "/upstream.py",
        )
        upstream_started = True
        with httpx.Client(
            base_url=f"https://localhost:{port}",
            verify=ssl.create_default_context(cafile=certificate),
            headers={"X-Requested-With": "XMLHttpRequest"},
            timeout=10,
        ) as client:
            eventually(lambda: client.get("/healthz").status_code == 200)
            signup = client.post(
                "/api/v1/auth/signup",
                json={"email": "owner@proxy.test", "name": "Owner", "password": "local-https-test-password"},
                headers={"X-Forwarded-Proto": "http", "Forwarded": "proto=http;host=attacker.invalid", "X-Forwarded-Host": "attacker.invalid"},
            )
            assert signup.status_code == 200, signup.text
            yield client, signup, compose, control_plane, direct
    finally:
        if upstream_started:
            docker("rm", "-f", upstream)
        if started:
            docker("rm", "-f", edge)
        docker(*compose, "down", "--volumes", "--remove-orphans")


def test_https_session_cookie_is_secure_despite_forged_forwarding(https_deployment):
    client, signup, _, _, direct = https_deployment
    cookies = SimpleCookie()
    cookies.load(signup.headers["set-cookie"])
    session = cookies["airllm_session"]
    assert session["secure"]
    assert session["httponly"]
    assert session["samesite"].lower() == "lax"
    assert session["path"] == "/"
    assert not session["domain"]
    assert payload(client.get("/api/v1/auth/me"))["email"] == "owner@proxy.test"
    with httpx.Client(base_url=direct, cookies=client.cookies) as insecure:
        assert insecure.get("/api/v1/auth/me").status_code == 401


def test_private_api_and_inference_responses_are_not_cacheable(https_deployment):
    client, signup, _, _, _ = https_deployment
    for response in (signup, client.get("/api/v1/auth/me"), client.get("/api/v1/not-a-resource"), client.post("/inf/v1/chat/completions", json={})):
        assert response.headers.get("cache-control") == "no-store", (response.url, response.headers)
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_public_proxy_discards_untrusted_forwarding_identity(https_deployment):
    _, _, compose, control_plane, direct = https_deployment
    sentinel = "203.0.113.222"
    response = httpx.get(
        direct + "/api/v1/auth/me?proxy-probe=forwarded",
        headers={"X-Forwarded-For": sentinel, "Forwarded": f"for={sentinel};proto=https", "X-Real-IP": sentinel},
    )
    assert response.status_code == 401
    container = docker(*compose, "ps", "-q", control_plane)
    eventually(lambda: "proxy-probe=forwarded" in docker("logs", container))
    logs = docker("logs", container)
    assert sentinel not in logs


@pytest.mark.parametrize(
    "path", ["/api/v1/not-a-resource", "/inf/v1/not-a-resource", "/api/%2e%2e/inf/v1/chat/completions", "/inf/%2e%2e/api/v1/auth/me"]
)
def test_api_routing_does_not_fall_back_to_the_console(https_deployment, path):
    client, _, _, _, _ = https_deployment
    response = client.get(path)
    assert response.status_code in {401, 404, 405}
    assert "<!doctype html>" not in response.text.lower()
    assert "set-cookie" not in response.headers


def test_forged_forwarded_host_cannot_change_redirect_origin(https_deployment):
    client, _, _, _, _ = https_deployment
    response = client.get(
        "/api/v1/auth/me/",
        headers={"X-Forwarded-Host": "attacker.invalid", "Forwarded": "host=attacker.invalid;proto=http", "X-Forwarded-Proto": "http"},
        follow_redirects=False,
    )
    assert response.status_code == 307
    assert response.headers["location"].startswith(str(client.base_url))


def test_internal_plane_ports_are_not_published(https_deployment):
    _, _, compose, control_plane, _ = https_deployment
    services = (control_plane,) if control_plane == "airllm" else (control_plane, "data-plane-1", "data-plane-2")
    for service in services:
        container = docker(*compose, "ps", "-q", service)
        bindings = json.loads(docker("inspect", "--format", "{{json .HostConfig.PortBindings}}", container))
        assert not bindings.get("8000/tcp")
        assert not bindings.get("8081/tcp")


def test_https_inference_and_minted_secrets_remain_private(https_deployment):
    client, _, _, _, _ = https_deployment
    org = payload(client.post("/api/v1/enroll/org", json={"name": "HTTPS"}))
    scope = f"/api/v1/orgs/{org['id']}"
    workspace = payload(client.post(scope + "/workspaces", json={"name": "default"}))
    minted = client.post(f"{scope}/workspaces/{workspace['id']}/inference-keys", json={"label": "https"})
    key = payload(minted)
    assert minted.headers["cache-control"] == "no-store"
    payload(client.post("/api/v1/instance/taxonomy/providers", json={"provider_id": "deployment", "base_url": "http://deployment-upstream:9000"}))
    payload(
        client.post(
            "/api/v1/instance/taxonomy/models",
            json={"model_id": "deployment-echo", "provider_id": "deployment", "input_modalities": ["text"], "output_modalities": ["text"]},
        )
    )
    payload(client.post(scope + "/provider-credentials", json={"provider": "deployment", "value": "deployment-test-key"}))
    body = {"model": "deployment-echo", "messages": [{"role": "user", "content": "hi"}]}
    headers = {"Authorization": f"Bearer {key['token']}"}
    path = "/inf/v1/chat/completions"
    eventually(lambda: client.post(path, headers=headers, json=body).status_code == 200)
    for stream in (False, True):
        response = client.post(path, headers=headers, json={**body, "stream": stream})
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        assert "deployment ready" in response.text
