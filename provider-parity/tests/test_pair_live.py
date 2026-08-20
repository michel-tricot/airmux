from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, NamedTuple, cast

import pytest

from provider_parity.gateway import Gateway
from provider_parity.models import Case, EgressKind, Experiment, Oracle, Plan, Request, Target, Transport
from provider_parity.runner import execute

if TYPE_CHECKING:
    from collections.abc import Mapping

IMAGE_DATA = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2s0UAAAAASUVORK5CYII="


class ProviderHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/readyz":
            self._send_json({"status": "ready"})
            return
        self.send_error(404)

    def do_POST(self) -> None:
        server = self.server
        assert isinstance(server, ProviderServer)
        request = json.loads(self.rfile.read(int(self.headers["content-length"])))
        server.models.append(request["model"])
        server.requests.append(request)
        if self.path.startswith("/inf") and server.gateway_status is not None:
            self._send_json({"type": "error", "error": {"type": "authentication_error", "message": "invalid inference key"}}, server.gateway_status)
            return
        if self.path.endswith("/responses"):
            self._send_json(
                {
                    "id": "resp-parity",
                    "object": "response",
                    "created_at": 1,
                    "model": request["model"],
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "id": "msg-parity",
                            "role": "assistant",
                            "status": "completed",
                            "content": [{"type": "output_text", "text": "ok", "annotations": []}],
                        }
                    ],
                    "usage": {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4},
                }
            )
            return
        if self.path.endswith("/messages"):
            self._send_json(
                {
                    "id": "msg-parity",
                    "type": "message",
                    "role": "assistant",
                    "model": request["model"],
                    "content": [{"type": "text", "text": "ok"}],
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {"input_tokens": 3, "output_tokens": 1},
                }
            )
            return
        if request.get("stream"):
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.end_headers()
            events = [
                {"id": "chatcmpl-parity", "model": request["model"], "choices": [{"index": 0, "delta": {"content": "o"}, "finish_reason": None}]},
                {"id": "chatcmpl-parity", "model": request["model"], "choices": [{"index": 0, "delta": {"content": "k"}, "finish_reason": None}]},
                {"id": "chatcmpl-parity", "model": request["model"], "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                {
                    "id": "chatcmpl-parity",
                    "model": request["model"],
                    "choices": [],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
                },
            ]
            for event in events:
                self.wfile.write(b"data: " + json.dumps(event).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        payload = {
            "id": "chatcmpl-parity",
            "model": request["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
        }
        self._send_json(payload)

    def _send_json(self, payload: dict[str, object], status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 signature belongs to BaseHTTPRequestHandler
        return


class ProviderServer(ThreadingHTTPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), ProviderHandler)
        self.models: list[str] = []
        self.requests: list[dict[str, object]] = []
        self.gateway_status: int | None = None

    def start(self) -> None:
        threading.Thread(target=self.serve_forever, daemon=True).start()


class SurfacePair(NamedTuple):
    provider_id: str
    surface_id: str
    endpoint: str
    egress_kind: EgressKind
    driver_id: str
    sdk_type: str


@pytest.mark.parametrize("transport", ["buffered", "streamed"])
def test_the_same_sdk_case_runs_directly_and_through_the_configured_gateway(monkeypatch, transport: Transport):
    provider = ProviderServer()
    provider.start()
    monkeypatch.setenv("STUB_API_KEY", "sk-provider")
    target = Target(
        provider_id="stub",
        surface_id="oai",
        endpoint="chat/completions",
        egress_kind="openai_compatible",
        base_url=f"http://127.0.0.1:{provider.server_port}/v1",
        credential_env="STUB_API_KEY",
        auth="bearer",
        headers={},
        model_id="stub/model",
        upstream_model="upstream-model",
        context_window=8192,
        max_output_tokens=1024,
        input_modalities=frozenset({"text"}),
        capabilities=frozenset({"streaming"}),
        parameter_support={},
    )
    case = Case(
        id="text.live",
        title="Live pair",
        request=Request(messages=({"role": "user", "content": "Reply with ok"},)),
        oracle=Oracle(text_contains="ok"),
    )
    plan = Plan(experiments=(Experiment(target=target, case=case, driver_id="openai", transport=transport),))

    try:
        (result,) = execute(plan, Gateway(base_url=f"http://127.0.0.1:{provider.server_port}", api_key="sk-inf-parity"))
    finally:
        provider.shutdown()
        provider.server_close()

    assert result.comparison.verdict == "parity"
    expected_type = "ChatCompletion" if transport == "buffered" else "Stream[ChatCompletionChunk]"
    assert result.direct.sdk_type == expected_type
    assert result.gateway.sdk_type == expected_type
    assert provider.models == ["upstream-model", "stub/model"]


@pytest.mark.parametrize(
    "surface",
    [
        SurfacePair("responses", "oai_responses", "responses", "openai_responses", "openai", "Response"),
        SurfacePair("messages", "anthropic", "messages", "anthropic", "anthropic", "Message"),
    ],
)
def test_each_native_sdk_surface_is_paired_through_the_gateway(monkeypatch, surface: SurfacePair):
    provider = ProviderServer()
    provider.start()
    credential_env = f"{surface.provider_id.upper()}_API_KEY"
    monkeypatch.setenv(credential_env, "sk-provider")
    target = Target(
        provider_id=surface.provider_id,
        surface_id=surface.surface_id,
        endpoint=surface.endpoint,
        egress_kind=surface.egress_kind,
        base_url=f"http://127.0.0.1:{provider.server_port}/v1",
        credential_env=credential_env,
        auth="header_key:x-api-key" if surface.endpoint == "messages" else "bearer",
        headers={},
        model_id=f"{surface.provider_id}/model",
        upstream_model="upstream-model",
        context_window=8192,
        max_output_tokens=1024,
        input_modalities=frozenset({"text"}),
        capabilities=frozenset(),
        parameter_support={},
    )
    case = Case(
        id="text.live",
        title="Live pair",
        request=Request(messages=({"role": "user", "content": "Reply with ok"},)),
        oracle=Oracle(text_contains="ok"),
    )
    plan = Plan(experiments=(Experiment(target=target, case=case, driver_id=surface.driver_id, transport="buffered"),))

    try:
        (result,) = execute(plan, Gateway(base_url=f"http://127.0.0.1:{provider.server_port}", api_key="sk-inf-parity"))
    finally:
        provider.shutdown()
        provider.server_close()

    assert result.comparison.verdict == "parity"
    assert result.direct.sdk_type == surface.sdk_type
    assert result.gateway.sdk_type == surface.sdk_type
    assert provider.models == ["upstream-model", f"{surface.provider_id}/model"]


@pytest.mark.parametrize(
    ("surface", "content_key", "block_type"),
    [
        (SurfacePair("chat", "oai", "chat/completions", "openai_compatible", "openai", "ChatCompletion"), "messages", "image_url"),
        (SurfacePair("responses", "oai_responses", "responses", "openai_responses", "openai", "Response"), "input", "input_image"),
        (SurfacePair("messages", "anthropic", "messages", "anthropic", "anthropic", "Message"), "messages", "image"),
    ],
)
def test_image_input_uses_each_sdk_spelling_on_both_paths(monkeypatch, surface: SurfacePair, content_key: str, block_type: str):
    provider = ProviderServer()
    provider.start()
    credential_env = f"{surface.provider_id.upper()}_API_KEY"
    monkeypatch.setenv(credential_env, "sk-provider")
    target = Target(
        provider_id=surface.provider_id,
        surface_id=surface.surface_id,
        endpoint=surface.endpoint,
        egress_kind=surface.egress_kind,
        base_url=f"http://127.0.0.1:{provider.server_port}/v1",
        credential_env=credential_env,
        auth="header_key:x-api-key" if surface.endpoint == "messages" else "bearer",
        headers={},
        model_id=f"{surface.provider_id}/model",
        upstream_model="upstream-model",
        context_window=8192,
        max_output_tokens=1024,
        input_modalities=frozenset({"text", "image"}),
        capabilities=frozenset(),
        parameter_support={},
    )
    case = Case(
        id="modalities.image",
        title="Image input",
        request=Request(
            messages=(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Reply with ok"},
                        {"type": "image", "media_type": "image/png", "data": IMAGE_DATA},
                    ],
                },
            )
        ),
        oracle=Oracle(text_contains="ok"),
    )
    plan = Plan(experiments=(Experiment(target=target, case=case, driver_id=surface.driver_id, transport="buffered"),))

    try:
        (result,) = execute(plan, Gateway(base_url=f"http://127.0.0.1:{provider.server_port}", api_key="sk-inf-parity"))
    finally:
        provider.shutdown()
        provider.server_close()

    assert result.comparison.verdict == "parity"
    for request in provider.requests:
        messages = request[content_key]
        assert isinstance(messages, list)
        message = cast("Mapping[str, object]", messages[0])
        content = message["content"]
        assert isinstance(content, list)
        block = cast("Mapping[str, object]", content[1])
        assert block["type"] == block_type


@pytest.mark.parametrize(
    "surface",
    [
        SurfacePair("chat", "oai", "chat/completions", "openai_compatible", "openai", "ChatCompletion"),
        SurfacePair("messages", "anthropic", "messages", "anthropic", "anthropic", "Message"),
    ],
)
def test_gateway_authentication_failure_is_inconclusive(monkeypatch, surface: SurfacePair):
    provider = ProviderServer()
    provider.gateway_status = 401
    provider.start()
    credential_env = f"{surface.provider_id.upper()}_API_KEY"
    monkeypatch.setenv(credential_env, "sk-provider")
    target = Target(
        provider_id=surface.provider_id,
        surface_id=surface.surface_id,
        endpoint=surface.endpoint,
        egress_kind=surface.egress_kind,
        base_url=f"http://127.0.0.1:{provider.server_port}/v1",
        credential_env=credential_env,
        auth="header_key:x-api-key" if surface.endpoint == "messages" else "bearer",
        headers={},
        model_id=f"{surface.provider_id}/model",
        upstream_model="upstream-model",
        context_window=8192,
        max_output_tokens=1024,
        input_modalities=frozenset({"text"}),
        capabilities=frozenset(),
        parameter_support={},
    )
    case = Case(
        id="text.live",
        title="Live pair",
        request=Request(messages=({"role": "user", "content": "Reply with ok"},)),
        oracle=Oracle(text_contains="ok"),
    )
    plan = Plan(experiments=(Experiment(target=target, case=case, driver_id=surface.driver_id, transport="buffered"),))

    try:
        (result,) = execute(plan, Gateway(base_url=f"http://127.0.0.1:{provider.server_port}", api_key="invalid"))
    finally:
        provider.shutdown()
        provider.server_close()

    assert result.direct.outcome == "success"
    assert result.gateway.outcome == "inconclusive"
    assert result.gateway.error_code == "gateway_authentication"
    assert result.comparison.verdict == "inconclusive"
