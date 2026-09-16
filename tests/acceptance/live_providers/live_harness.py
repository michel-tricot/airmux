from __future__ import annotations

import contextlib
import json
import os
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

import httpx
import pytest
from pydantic import TypeAdapter
from tests.acceptance.gateway.gateway_harness import Gateway

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from tests.acceptance.gateway.upstream import Family

    from contract import UsageEvent
    from contract.model_types import Capability


@dataclass(frozen=True)
class ProviderCase:
    family: Family
    provider: str
    model: str
    base_url: str
    credential: str
    output_limit: str
    prices: tuple[float, float, float, float]
    aliases: dict[str, str]
    context_window: int
    capabilities: tuple[Capability, ...]


CASES: dict[Family, ProviderCase] = {
    "openai_compatible": ProviderCase(
        "openai_compatible",
        "openai",
        "gpt-4.1-mini-2025-04-14",
        "https://api.openai.com/v1",
        "OPENAI_API_KEY",
        "max_completion_tokens",
        (0.4, 1.6, 0.1, 0),
        {"max_tokens": "max_completion_tokens"},
        1047576,
        ("streaming", "tools", "structured_output"),
    ),
    "openai_responses": ProviderCase(
        "openai_responses",
        "openai",
        "gpt-4.1-mini-2025-04-14",
        "https://api.openai.com/v1",
        "OPENAI_API_KEY",
        "max_output_tokens",
        (0.4, 1.6, 0.1, 0),
        {},
        1047576,
        ("streaming", "tools", "structured_output"),
    ),
    "anthropic": ProviderCase(
        "anthropic",
        "anthropic",
        "claude-haiku-4-5-20251001",
        "https://api.anthropic.com/v1",
        "ANTHROPIC_API_KEY",
        "max_tokens",
        (1, 5, 0.1, 1.25),
        {},
        200000,
        ("streaming", "tools", "structured_output", "reasoning"),
    ),
}


class RequestBudget:
    def __init__(self) -> None:
        self.requests = 0
        self.lock = threading.Lock()

    def reserve(self, body: dict[str, object], limit_field: str) -> bool:
        limit = body.get(limit_field)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 0 < limit <= 1280:
            return False
        with self.lock:
            if self.requests >= 30:
                return False
            self.requests += 1
            return True


@dataclass(frozen=True)
class Delivery:
    request: dict[str, object]
    status: int
    body: bytes


class RecordingProvider(ThreadingHTTPServer):
    def __init__(self, case: ProviderCase, budget: RequestBudget, *, unavailable: bool = False) -> None:
        super().__init__(("127.0.0.1", 0), RecordingHandler)
        self.case = case
        self.budget = budget
        self.unavailable = unavailable
        self.deliveries: list[Delivery] = []
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}"

    def close(self) -> None:
        self.shutdown()
        self.server_close()
        self.thread.join(timeout=5)


class RecordingHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        provider = self.server
        assert isinstance(provider, RecordingProvider)
        payload = self.rfile.read(int(self.headers["content-length"]))
        request = TypeAdapter(dict[str, object]).validate_json(payload, strict=True)
        if provider.unavailable:
            self.respond(503, request, b'{"error":{"code":"api_error","message":"forced upstream unavailable"}}')
            return
        if len(payload) > 8192 or not provider.budget.reserve(request, provider.case.output_limit):
            self.respond(400, request, b'{"error":{"code":"live_test_budget","message":"live test request limit exceeded"}}')
            return
        headers = {
            name: value
            for name, value in self.headers.items()
            if name.lower() in {"authorization", "x-api-key", "anthropic-version", "anthropic-beta", "content-type"}
        }
        try:
            with (
                httpx.Client(timeout=90) as client,
                client.stream("POST", provider.case.base_url + self.path, headers=headers, content=payload) as response,
            ):
                self.send_response(response.status_code)
                self.send_header("Content-Type", response.headers.get("content-type", "application/json"))
                self.end_headers()
                fragments: list[bytes] = []
                for fragment in response.iter_bytes():
                    fragments.append(fragment)
                    with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                        self.wfile.write(fragment)
                        self.wfile.flush()
                with provider.lock:
                    provider.deliveries.append(Delivery(request, response.status_code, b"".join(fragments)))
        except httpx.HTTPError:
            self.close_connection = True

    def respond(self, status: int, request: dict[str, object], body: bytes) -> None:
        provider = self.server
        assert isinstance(provider, RecordingProvider)
        with provider.lock:
            provider.deliveries.append(Delivery(request, status, body))
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 parameter name is required by BaseHTTPRequestHandler
        return


def native_object(value: object) -> dict[str, object]:
    return TypeAdapter(dict[str, object]).validate_python(value, strict=True)


def native_events(delivery: Delivery) -> list[dict[str, object]]:
    return [
        TypeAdapter(dict[str, object]).validate_json(line[6:], strict=True)
        for line in delivery.body.splitlines()
        if line.startswith(b"data: ") and line != b"data: [DONE]"
    ]


def chat_usage(delivery: Delivery) -> tuple[int, int, int, int]:
    response = next(event for event in native_events(delivery) if event.get("usage")) if delivery.request.get("stream") else json.loads(delivery.body)
    usage = native_object(response["usage"])
    cache = native_object(usage.get("prompt_tokens_details", {}))
    return TypeAdapter(tuple[int, int, int, int]).validate_python(
        (usage["prompt_tokens"], usage["completion_tokens"], cache.get("cached_tokens", 0), 0), strict=True
    )


def responses_usage(delivery: Delivery) -> tuple[int, int, int, int]:
    response = (
        next(event["response"] for event in native_events(delivery) if event["type"] == "response.completed")
        if delivery.request.get("stream")
        else json.loads(delivery.body)
    )
    usage = native_object(native_object(response)["usage"])
    cache = native_object(usage.get("input_tokens_details", {}))
    return TypeAdapter(tuple[int, int, int, int]).validate_python(
        (usage["input_tokens"], usage["output_tokens"], cache.get("cached_tokens", 0), 0), strict=True
    )


def anthropic_usage(delivery: Delivery) -> tuple[int, int, int, int]:
    if delivery.request.get("stream"):
        events = native_events(delivery)
        started = native_object(next(event["message"] for event in events if event["type"] == "message_start"))
        final = next(event["usage"] for event in events if event["type"] == "message_delta")
        usage = {**native_object(started["usage"]), **native_object(final)}
    else:
        usage = native_object(json.loads(delivery.body)["usage"])
    counts = TypeAdapter(tuple[int, int, int, int]).validate_python(
        (usage["input_tokens"], usage["output_tokens"], usage.get("cache_read_input_tokens", 0), usage.get("cache_creation_input_tokens", 0)),
        strict=True,
    )
    fresh, output, reads, writes = counts
    return fresh + reads + writes, output, reads, writes


USAGE_READERS: dict[Family, Callable[[Delivery], tuple[int, int, int, int]]] = {
    "openai_compatible": chat_usage,
    "openai_responses": responses_usage,
    "anthropic": anthropic_usage,
}


class LiveGateway:
    def __init__(self, directory: Path, case: ProviderCase, budget: RequestBudget) -> None:
        self.case = case
        self.gateway = Gateway(directory / "gateway", directory.name)
        self.provider = RecordingProvider(case, budget)
        self.providers = [self.provider]
        self.gateway.taxonomy = {
            "providers": [
                {
                    "provider_id": case.provider,
                    "kind": case.family,
                    "base_url": self.provider.url,
                    "param_aliases": case.aliases,
                }
            ],
            "models": [
                {
                    "model_id": "model-a",
                    "provider_id": case.provider,
                    "upstream_model": case.model,
                    "input_price_per_mtok": case.prices[0],
                    "output_price_per_mtok": case.prices[1],
                    "cache_read_price_per_mtok": case.prices[2],
                    "cache_write_price_per_mtok": case.prices[3],
                    "context_window": case.context_window,
                    "max_output_tokens": 1280,
                    "input_modalities": ["text"],
                    "output_modalities": ["text"],
                    "capabilities": case.capabilities,
                }
            ],
        }

    def request(
        self, *, stream: bool = False, model: str = "model-a", max_tokens: int = 128, body: dict[str, object] | None = None
    ) -> httpx.Response:
        return self.gateway.request("canonical", stream=stream, model=model, max_tokens=max_tokens, body=body, timeout_s=90)

    def assert_metering(self, event: UsageEvent) -> None:
        assert event.status == "ok"
        assert event.provider_id == self.case.provider
        with self.provider.lock:
            (delivery,) = self.provider.deliveries
        assert delivery.status == 200
        tokens = USAGE_READERS[self.case.family](delivery)
        assert (event.input_tokens, event.output_tokens, event.cache_read_tokens, event.cache_write_tokens) == tokens
        assert all(count >= 0 for count in tokens)
        assert tokens[0] > 0
        assert tokens[1] > 0
        total, output, reads, writes = tokens
        input_price, output_price, read_price, write_price = self.case.prices
        input_cost = ((total - reads - writes) * input_price + reads * read_price + writes * write_price) / 1000000
        output_cost = output * output_price / 1000000
        assert (event.cost_input_usd, event.cost_output_usd, event.cost_usd) == pytest.approx(
            (input_cost, output_cost, input_cost + output_cost), rel=1e-12, abs=1e-15
        )

    def close(self) -> None:
        self.gateway.sensitive_values = (os.environ[self.case.credential],)
        self.gateway.close()
        for provider in self.providers:
            provider.close()
