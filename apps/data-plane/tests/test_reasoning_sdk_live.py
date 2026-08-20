from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from anthropic import Anthropic
from openai import OpenAI
from starlette.responses import JSONResponse
from starlette.routing import Route

from data_plane.app import load_app

if TYPE_CHECKING:
    from starlette.requests import Request


async def chat_upstream(request: Request) -> JSONResponse:
    body = await request.json()
    if body.get("reasoning_effort") != "high":
        return JSONResponse({"error": {"message": "missing reasoning_effort"}}, status_code=400)
    return JSONResponse(
        {
            "id": "chatcmpl-live",
            "choices": [{"message": {"role": "assistant", "content": "chat ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 2},
        }
    )


async def responses_upstream(request: Request) -> JSONResponse:
    body = await request.json()
    if body.get("reasoning") != {"effort": "high", "summary": "concise"}:
        return JSONResponse({"error": {"message": "missing reasoning config"}}, status_code=400)
    return JSONResponse(
        {
            "id": "resp_live",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "id": "msg_live",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "responses ok", "annotations": []}],
                }
            ],
            "usage": {"input_tokens": 2, "output_tokens": 2},
        }
    )


async def messages_upstream(request: Request) -> JSONResponse:
    body = await request.json()
    if body.get("thinking") != {"type": "adaptive"} or body.get("output_config") != {"effort": "high"}:
        return JSONResponse({"type": "error", "error": {"type": "invalid_request", "message": "missing thinking config"}}, status_code=400)
    return JSONResponse(
        {
            "id": "msg_live",
            "content": [{"type": "thinking", "thinking": "brief", "signature": "sig_live"}, {"type": "text", "text": "messages ok"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 2, "output_tokens": 2},
        }
    )


def sdk_compat_app():
    app = load_app()
    app.routes[:0] = [
        Route("/provider/chat/completions", chat_upstream, methods=["POST"]),
        Route("/provider/responses", responses_upstream, methods=["POST"]),
        Route("/provider/messages", messages_upstream, methods=["POST"]),
    ]
    return app


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _write_config(tmp_path: Path, port: int) -> Path:
    bundle = tmp_path / "bundle.yml"
    bundle.write_text(
        f"""keys: [sk-inf-live]
providers:
  - {{provider_id: chat, kind: openai_compatible, base_url: 'http://127.0.0.1:{port}/provider'}}
  - {{provider_id: responses, kind: openai_responses, base_url: 'http://127.0.0.1:{port}/provider'}}
  - {{provider_id: messages, kind: anthropic, base_url: 'http://127.0.0.1:{port}/provider'}}
models:
  - model_id: chat-model
    provider_id: chat
    upstream_model: chat-upstream
    input_price_per_mtok: 1
    output_price_per_mtok: 1
    cache_read_price_per_mtok: 1
    cache_write_price_per_mtok: 1
    context_window: 1000
    capabilities: [reasoning]
  - model_id: responses-model
    provider_id: responses
    upstream_model: responses-upstream
    input_price_per_mtok: 1
    output_price_per_mtok: 1
    cache_read_price_per_mtok: 1
    cache_write_price_per_mtok: 1
    context_window: 1000
    capabilities: [reasoning]
  - model_id: messages-model
    provider_id: messages
    upstream_model: messages-upstream
    input_price_per_mtok: 1
    output_price_per_mtok: 1
    cache_read_price_per_mtok: 1
    cache_write_price_per_mtok: 1
    context_window: 1000
    capabilities: [reasoning]
""",
        encoding="utf-8",
    )
    config = tmp_path / "airllm.yml"
    config.write_text(
        f"""data_plane:
  bundle: {{kind: local, path: '{bundle}'}}
  events: {{kind: devnull}}
  secrets: {{kind: env}}
""",
        encoding="utf-8",
    )
    return config


def test_native_sdk_reasoning_controls_cross_a_running_data_plane(tmp_path: Path):
    port = _free_port()
    config = _write_config(tmp_path, port)
    repo = Path(__file__).resolve().parents[3]
    python_path = [repo / "apps/data-plane/src", repo / "lib/contract/src", repo / "lib/api-models/src", Path(__file__).parent]
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([*(str(path) for path in python_path), os.environ.get("PYTHONPATH", "")]),
        "GW_CONFIG": str(config),
        "CHAT_API_KEY": "chat-secret",
        "RESPONSES_API_KEY": "responses-secret",
        "MESSAGES_API_KEY": "messages-secret",
    }
    process = subprocess.Popen(  # noqa: S603 trusted interpreter and local test application
        [
            sys.executable,
            "-m",
            "uvicorn",
            "test_reasoning_sdk_live:sdk_compat_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "error",
        ],
        cwd=Path(__file__).parent,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/readyz", timeout=0.2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.02)
        else:
            raise AssertionError(process.communicate(timeout=1)[0])

        openai = OpenAI(base_url=f"http://127.0.0.1:{port}/inf/v1", api_key="sk-inf-live")
        chat = openai.chat.completions.create(
            model="chat-model",
            messages=[{"role": "user", "content": "hi"}],
            reasoning_effort="high",
        )
        assert chat.choices[0].message.content == "chat ok"

        response = openai.responses.create(
            model="responses-model",
            input="hi",
            reasoning={"effort": "high", "summary": "concise"},
        )
        assert response.output_text == "responses ok"

        anthropic = Anthropic(base_url=f"http://127.0.0.1:{port}/inf", api_key="sk-inf-live")
        message = anthropic.messages.create(
            model="messages-model",
            max_tokens=64,
            messages=[{"role": "user", "content": "hi"}],
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
        )
        assert message.content[-1].type == "text"
        assert message.content[-1].text == "messages ok"
    finally:
        process.terminate()
        process.wait(timeout=5)
