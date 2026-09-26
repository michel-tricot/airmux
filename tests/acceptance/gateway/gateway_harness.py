from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypedDict
from uuid import UUID

import httpx
import pytest
import yaml
from pydantic import TypeAdapter
from tests.acceptance.process_harness import uvicorn_port
from upstream import UPSTREAM_KEY, Family, Upstream

from contract import UsageEvent, uuid7

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

Dialect = Literal["openai_chat_completions", "openai_responses", "anthropic"]
PROTOCOLS = json.loads((Path(__file__).parent / "protocols.json").read_text())
DIALECTS = tuple(PROTOCOLS["ingress"])
FAMILIES = tuple(PROTOCOLS["egress"])
INFERENCE_KEY = "sk-inf-integration-first"
SECOND_KEY = "sk-inf-integration-second"
LOCAL_WORKSPACE = str(UUID(int=0))
REQUEST_INPUTS: dict[Dialect, dict[str, object]] = {
    "openai_chat_completions": {"messages": [{"role": "user", "content": "hi"}]},
    "openai_responses": {"input": "hi"},
    "anthropic": {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 128},
}
ERROR_FIELDS: dict[Dialect, str] = {
    "openai_chat_completions": "code",
    "openai_responses": "code",
    "anthropic": "type",
}


def eventually(check: Callable[[], bool], timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with contextlib.suppress(httpx.HTTPError):
            if check():
                return
        time.sleep(0.05)
    assert check(), "gateway did not reach the expected state before the deadline"


def request_body(dialect: Dialect, model: str = "model-a", **parameters: object) -> dict[str, object]:
    return {"model": model, **deepcopy(REQUEST_INPUTS[dialect]), **parameters}


def text_of(dialect: Dialect, response: httpx.Response) -> str:
    body = response.json()
    if dialect == "openai_chat_completions":
        return body["choices"][0]["message"]["content"]
    if dialect == "openai_responses":
        return "".join(part["text"] for item in body["output"] if item["type"] == "message" for part in item["content"])
    return "".join(part["text"] for part in body["content"] if part["type"] == "text")


def stream_payloads(response: httpx.Response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ") and line != "data: [DONE]"]


def streamed_text(dialect: Dialect, response: httpx.Response) -> str:
    payloads = stream_payloads(response)
    if dialect == "openai_chat_completions":
        return "".join(choice["delta"].get("content", "") for event in payloads for choice in event.get("choices", []))
    if dialect == "openai_responses":
        return "".join(event["delta"] for event in payloads if event.get("type") == "response.output_text.delta")
    return "".join(
        event["delta"]["text"] for event in payloads if event.get("type") == "content_block_delta" and event["delta"]["type"] == "text_delta"
    )


def error_of(dialect: Dialect, response: httpx.Response) -> str:
    error = response.json()["error"]
    return error[ERROR_FIELDS[dialect]]


class GatewayKey(TypedDict):
    token: str
    user_id: str


class GatewayBundle(TypedDict):
    keys: list[GatewayKey]
    taxonomy: str
    policies: list[dict[str, object]]


class Gateway:
    def __init__(self, directory: Path, scenario: str) -> None:
        self.directory = directory
        self.scenario = scenario
        self.directory.mkdir()
        self.config_path = directory / "airmux.yml"
        self.taxonomy_path = directory / "taxonomy.yml"
        self.bundle_path = directory / "bundle.yml"
        self.events_path = directory / "usage/events.jsonl"
        self.reload_interval_s = 0.05
        self.dev = False
        self.executable = os.environ.get("AIRMUX_GATEWAY_BIN", str(Path(sys.executable).parent / "airmux"))
        self.environment = {**os.environ, "STUB_API_KEY": UPSTREAM_KEY, "BACKUP_API_KEY": UPSTREAM_KEY, "DOCKER_HOST": "unix:///no-docker.sock"}
        self.providers: list[Upstream] = []
        self.sensitive_values: tuple[str, ...] = ()
        self.taxonomy: dict[str, list[dict[str, object]]] = {"providers": [], "models": []}
        self.bundle: GatewayBundle = {
            "keys": [{"token": INFERENCE_KEY, "user_id": str(uuid7())}, {"token": SECOND_KEY, "user_id": str(uuid7())}],
            "taxonomy": "taxonomy.yml",
            "policies": [],
        }
        self.process: subprocess.Popen[bytes] | None = None
        self.log = (directory / "gateway.log").open("a", encoding="utf-8")
        self.port: int | None = None
        self.url = ""

    def add_provider(self, family: Family = "openai_compatible", name: str = "stub", models: tuple[str, ...] = ("model-a", "model-b")) -> Upstream:
        provider = Upstream(family, self.directory / f"upstream-{name}.json")
        self.providers.append(provider)
        self.taxonomy["providers"].append({"provider_id": name, "kind": family, "base_url": provider.url})
        self.taxonomy["models"].extend(
            [
                {
                    "model_id": model,
                    "provider_id": name,
                    "upstream_model": f"upstream-{model}",
                    "input_price_per_mtok": "2",
                    "output_price_per_mtok": "5",
                    "cache_read_price_per_mtok": "0.25",
                    "cache_write_price_per_mtok": "2.5",
                    "context_window": 128000,
                    "max_output_tokens": 4096,
                    "input_modalities": ["text", "image", "pdf"],
                    "output_modalities": ["text"],
                    "capabilities": ["streaming", "tools", "reasoning", "structured_output"],
                }
                for model in models
            ]
        )
        return provider

    def add_policy(
        self,
        actions: list[dict[str, object]],
        *,
        match: dict[str, object] | None = None,
        target: dict[str, object] | None = None,
    ) -> None:
        rules = [{"match": match or {"kind": "all_requests"}, "action": action} for action in actions]
        self.bundle["policies"] = [
            *self.bundle["policies"],
            {
                "id": str(uuid7()),
                "workspace_id": LOCAL_WORKSPACE,
                "name": f"Policy {len(self.bundle['policies'])}",
                "definition": {"target": target or {"kind": "workspace"}, "rules": rules},
            },
        ]

    def write_files(self) -> None:
        for path, content in ((self.taxonomy_path, self.taxonomy), (self.bundle_path, self.bundle)):
            replacement = path.with_suffix(".new")
            replacement.write_text(yaml.safe_dump(content), encoding="utf-8")
            replacement.replace(path)
        self.config_path.write_text(
            yaml.safe_dump(
                {
                    "data_plane": {
                        "bundle": {"kind": "local", "path": "bundle.yml", "reload_interval_s": self.reload_interval_s},
                        "secrets": {"kind": "env"},
                        "events": {"kind": "file", "path": "usage/events.jsonl"},
                    }
                }
            ),
            encoding="utf-8",
        )

    def start(self, workers: int = 1) -> None:
        self.write_files()
        self.launch(workers)
        eventually(self.ready)

    def ready(self) -> bool:
        assert self.process is not None
        assert self.process.poll() is None, (self.directory / "gateway.log").read_text()
        if self.port is None:
            self.port = uvicorn_port(self.directory / "gateway.log")
            if self.port is None:
                return False
            self.url = f"http://127.0.0.1:{self.port}"
        return httpx.get(f"{self.url}/healthz", timeout=1).status_code == 200

    def launch(self, workers: int = 1) -> None:
        self.process = subprocess.Popen(  # noqa: S603 executable is the installed gateway supplied by the test environment
            [
                self.executable,
                "gateway",
                "serve",
                "--config",
                str(self.config_path),
                "--port",
                str(self.port or 0),
                "--workers",
                str(workers),
                *(["--dev"] if self.dev else []),
            ],
            cwd=self.directory.parent,
            env=self.environment,
            stdout=self.log,
            stderr=subprocess.STDOUT,
        )

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    def headers(self, _dialect: Dialect = "openai_chat_completions", key: str = INFERENCE_KEY) -> dict[str, str]:
        return {"Authorization": f"Bearer {key}"}

    def request(
        self,
        dialect: Dialect = "openai_chat_completions",
        *,
        model: str = "model-a",
        body: dict[str, object] | None = None,
        key: str = INFERENCE_KEY,
        timeout_s: float = 15,
        **parameters: object,
    ) -> httpx.Response:
        response = httpx.post(
            self.url + PROTOCOLS["ingress"][dialect],
            headers=self.headers(dialect, key),
            json=body if body is not None else {**request_body(dialect, model), **parameters},
            timeout=timeout_s,
        )
        with (self.directory / "responses.jsonl").open("a", encoding="utf-8") as responses:
            responses.write(json.dumps({"status": response.status_code, "body": response.text}, ensure_ascii=False) + "\n")
        return response

    def events(self, count: int) -> list[UsageEvent]:
        eventually(lambda: self.events_path.exists() and self.events_path.read_bytes().count(b"\n") >= count)
        contents = self.events_path.read_text(encoding="utf-8")
        assert contents.endswith("\n") or not contents
        events = TypeAdapter(list[UsageEvent]).validate_json("[" + ",".join(contents.splitlines()) + "]", strict=True)
        assert len(events) == count
        assert len({event.event_id for event in events}) == count
        assert all(event.event_id.version == 7 and event.request_id.version == 7 for event in events)
        assert all(event.org_id == UUID(int=0) and event.workspace_id == UUID(int=0) for event in events)
        assert all(event.cost_usd == event.cost_input_usd + event.cost_output_usd for event in events)
        assert all(secret not in contents for secret in (UPSTREAM_KEY, INFERENCE_KEY, SECOND_KEY))
        return events

    def close(self) -> None:
        for provider in self.providers:
            for reply in provider.replies.values():
                if reply.hold is not None:
                    reply.hold.set()
        self.stop()
        for provider in self.providers:
            provider.close()
        self.log.close()
        artifacts = os.environ.get("AIRMUX_GATEWAY_ARTIFACTS")
        if artifacts:
            destination = Path(artifacts) / self.scenario
            destination.mkdir(parents=True, exist_ok=True)
            secrets = (*self.sensitive_values, UPSTREAM_KEY, INFERENCE_KEY, SECOND_KEY, *(key["token"] for key in self.bundle["keys"]))
            for path in self.directory.rglob("*"):
                if path.is_file() and path.suffix in {".log", ".json", ".jsonl", ".yml", ".yaml"}:
                    contents = path.read_text(encoding="utf-8")
                    for secret in secrets:
                        contents = contents.replace(secret, "[REDACTED]")
                    target = destination / path.relative_to(self.directory)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(contents, encoding="utf-8")


@pytest.fixture
def gateway(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[Gateway]:
    gateway = Gateway(tmp_path / "gateway", request.node.name)
    try:
        yield gateway
    finally:
        gateway.close()
