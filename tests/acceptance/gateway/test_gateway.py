from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import httpx
import yaml
from tests.acceptance.process_harness import uvicorn_port

if TYPE_CHECKING:
    from collections.abc import Callable


class ProviderHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        request = json.loads(self.rfile.read(int(self.headers["content-length"])))
        if self.headers.get("authorization") != "Bearer upstream-test-key":
            self.send_error(401)
            return
        self.send_response(200)
        if request.get("stream"):
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            events = (
                {"id": "test", "choices": [{"index": 0, "delta": {"content": "hello"}, "finish_reason": None}]},
                {"id": "test", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                {"id": "test", "choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
            )
            for event in events:
                self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "id": "test",
                        "model": request["model"],
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                    }
                ).encode()
            )


def eventually(check: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    assert check()


def initialize_gateway(executable, taxonomy_path, directory, tmp_path, environment):
    initialized = subprocess.run(  # noqa: S603 trusted installed gateway executable
        [executable, "gateway", "init", "--taxonomy", str(taxonomy_path), "--directory", str(directory)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    key = (directory / "inference.key").read_text().strip()
    assert key not in initialized.stdout
    config_path = directory / "airmux.yml"
    config = yaml.safe_load(config_path.read_text())
    config["data_plane"]["bundle"]["reload_interval_s"] = 0.1
    config_path.write_text(yaml.safe_dump(config))
    subprocess.run([executable, "gateway", "validate", "--config", str(config_path)], cwd=tmp_path, env=environment, check=True)  # noqa: S603 trusted gateway
    return config_path, key


def verify_stream(client, headers, body):
    with client.stream("POST", "/inf/v1/chat/completions", headers=headers, json={**body, "stream": True}) as stream:
        assert stream.status_code == 200
        assert stream.headers["cache-control"] == "no-store, no-transform"
        assert stream.headers["x-accel-buffering"] == "no"
        assert UUID(stream.headers["x-request-id"]).version == 7
        events = list(stream.iter_lines())
    assert "data: [DONE]" in events
    assert any('"content":"hello"' in event.replace(" ", "") for event in events)


def verify_gateway_requests(client, headers, body, key):
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.headers["cache-control"] == "no-store"
    unauthorized = client.post("/inf/v1/chat/completions", json=body)
    assert unauthorized.status_code == 401
    assert unauthorized.headers["cache-control"] == "no-store"
    assert unauthorized.headers["www-authenticate"] == 'Bearer realm="airmux"'
    assert client.get("/inf/v1/models", headers={"x-api-key": key}).status_code == 200
    response = client.post("/inf/v1/chat/completions", headers=headers, json=body)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert UUID(response.headers["x-request-id"]).version == 7
    assert response.json()["choices"][0]["message"]["content"] == "hello"
    verify_stream(client, headers, body)


def test_installed_gateway_with_external_taxonomy(tmp_path):
    executable = os.environ.get("AIRMUX_GATEWAY_BIN", str(Path(sys.executable).parent / "airmux"))
    provider = ThreadingHTTPServer(("127.0.0.1", 0), ProviderHandler)
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    taxonomy_path = tmp_path / "taxonomy.yml"
    taxonomy = {
        "providers": [{"provider_id": "stub", "base_url": f"http://127.0.0.1:{provider.server_port}"}],
        "models": [{"model_id": "echo", "provider_id": "stub", "input_modalities": ["text"], "output_modalities": ["text"]}],
    }
    taxonomy_path.write_text(yaml.safe_dump(taxonomy))
    directory = tmp_path / "gateway"
    environment = {
        "PATH": os.environ["PATH"],
        "STUB_API_KEY": "upstream-test-key",
        "DOCKER_HOST": "unix:///no-docker.sock",
    }
    process = None
    try:
        config_path, key = initialize_gateway(executable, taxonomy_path, directory, tmp_path, environment)
        log_path = tmp_path / "gateway.log"
        with log_path.open("w") as log:
            process = subprocess.Popen(  # noqa: S603 trusted gateway
                [executable, "gateway", "serve", "--config", str(config_path), "--port", "0"],
                cwd=tmp_path,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            eventually(lambda: uvicorn_port(log_path) is not None)
            port = uvicorn_port(log_path)
            assert port is not None
            command = [executable, "gateway", "serve", "--config", str(config_path), "--port", str(port)]
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:
                eventually(lambda: client.get("/readyz").status_code == 200)
                headers = {"Authorization": f"Bearer {key}"}
                body = {"model": "echo", "messages": [{"role": "user", "content": "hi"}]}
                verify_gateway_requests(client, headers, body, key)
                taxonomy["models"][0]["model_id"] = "changed"
                taxonomy_path.write_text(yaml.safe_dump(taxonomy))
                changed = {**body, "model": "changed"}
                eventually(lambda: client.post("/inf/v1/chat/completions", headers=headers, json=changed).status_code == 200)
                assert client.post("/inf/v1/chat/completions", headers=headers, json=body).status_code != 200
                process.send_signal(signal.SIGTERM)
                assert process.wait(timeout=10) in {0, -signal.SIGTERM}
                process = subprocess.Popen(command, cwd=tmp_path, env=environment, stdout=log, stderr=subprocess.STDOUT)  # noqa: S603 trusted gateway
                eventually(lambda: client.get("/readyz").status_code == 200)
                assert client.post("/inf/v1/chat/completions", headers=headers, json=changed).status_code == 200
    finally:
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=10)
        provider.shutdown()
        provider.server_close()
        thread.join(timeout=5)
