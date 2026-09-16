from __future__ import annotations

import json
import signal
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
import yaml
from tests.installation.installation_support import run_cli


class Upstream(BaseHTTPRequestHandler):
    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if (
            self.path != "/chat/completions"
            or self.headers.get("Authorization") != "Bearer installation-test-key"
            or request["model"] != "upstream-echo"
            or request["messages"] != [{"role": "user", "content": "hello"}]
        ):
            self.send_error(400, "installed gateway sent an unexpected upstream request")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream" if request.get("stream") else "application/json")
        self.end_headers()
        completion = {
            "id": "chatcmpl-installation",
            "object": "chat.completion",
            "created": 1,
            "model": "upstream-echo",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "installation ready"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        }
        if request.get("stream"):
            chunk = {
                **completion,
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": "installation ready"}, "finish_reason": None}],
            }
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
            chunk["choices"] = [{"index": 0, "delta": {}, "finish_reason": "stop"}]
            self.wfile.write(f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode())
        else:
            self.wfile.write(json.dumps(completion).encode())


@pytest.fixture
def upstream_port():
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    try:
        yield upstream.server_port
    finally:
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=5)


def test_installed_gateway_serves_buffered_and_streaming_requests_and_shuts_down(installation, tmp_path, upstream_port):
    run_cli(installation, tmp_path, "gateway", "init")
    directory = tmp_path / ".airmux"
    key = (directory / "inference.key").read_text().strip()
    taxonomy = {
        "providers": [{"provider_id": "stub", "kind": "openai_compatible", "base_url": f"http://127.0.0.1:{upstream_port}"}],
        "models": [
            {
                "model_id": "echo",
                "provider_id": "stub",
                "upstream_model": "upstream-echo",
                "input_modalities": ["text"],
                "output_modalities": ["text"],
                "capabilities": ["streaming"],
            }
        ],
    }
    (directory / "taxonomy.yml").write_text(yaml.safe_dump(taxonomy), encoding="utf-8")
    executable, environment = installation
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    log_path = tmp_path / "gateway.log"
    with log_path.open("w") as log:
        process = subprocess.Popen(  # noqa: S603 executable is the candidate installed wheel
            [executable, "gateway", "serve", "--port", str(port)],
            cwd=tmp_path,
            env={**environment, "STUB_API_KEY": "installation-test-key"},
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    assert process.poll() is None, log_path.read_text()
                    try:
                        if client.get("/readyz").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    pytest.fail(f"installed gateway did not become ready:\n{log_path.read_text()}")
                headers = {"Authorization": f"Bearer {key}"}
                request = {"model": "echo", "messages": [{"role": "user", "content": "hello"}]}
                response = client.post("/inf/v1/chat/completions", headers=headers, json=request)
                assert response.status_code == 200, response.text
                assert response.json()["choices"][0]["message"]["content"] == "installation ready"
                with client.stream("POST", "/inf/v1/chat/completions", headers=headers, json={**request, "stream": True}) as response:
                    assert response.status_code == 200
                    assert response.headers["content-type"].startswith("text/event-stream")
                    events = [line[6:] for line in response.iter_lines() if line.startswith("data: ")]
                assert events[-1] == "[DONE]"
                chunks = [json.loads(event) for event in events[:-1]]
                assert "".join(choice["delta"].get("content", "") for chunk in chunks for choice in chunk["choices"]) == "installation ready"
                assert any(choice.get("finish_reason") == "stop" for chunk in chunks for choice in chunk["choices"])
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
            try:
                assert process.wait(timeout=10) in {0, -signal.SIGTERM}, log_path.read_text()
                assert "Application shutdown complete" in log_path.read_text(), log_path.read_text()
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                pytest.fail(f"installed gateway did not shut down after SIGTERM:\n{log_path.read_text()}")
