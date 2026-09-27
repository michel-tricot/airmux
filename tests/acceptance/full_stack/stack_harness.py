"""Black-box acceptance harness: real control plane, data plane and a stub upstream.

Everything is driven through the shipped console scripts and public HTTP surfaces, in an
isolated working directory. Nothing here imports control_plane or data_plane; if a test can
only be written by reaching into internals, that is a gap in the product, not the test.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import shutil
import signal
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TextIO
from uuid import uuid4

import asyncpg
import httpx
import pytest
import yaml
from dotenv import dotenv_values
from prometheus_client.parser import text_string_to_metric_families
from testcontainers.core.container import DockerContainer
from tests.acceptance.process_harness import uvicorn_port
from tests.diagnostics import retain_logs

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

ORG = "org-acc"
ADMIN_EMAIL = "admin@acceptance.test"
ADMIN_PASSWORD = "acceptance-admin-password"
MODEL = "echo"
ECHO_MODEL = "quirk-upstream"  # the stub echoes the received body back for this model, so tests can see the wire
STUB_API_KEY = "sk-acceptance-stub"
READY_TIMEOUT = 30.0

PG_IMAGE = "postgres:16"
PG_COMMAND = "postgres -c fsync=off -c synchronous_commit=off -c full_page_writes=off"

_pg: dict[str, DockerContainer | str] = {}
PG_ADMIN_ENV = "AIRMUX_TEST_PG_URL"


def metric(url: str, name: str) -> float:
    families = text_string_to_metric_families(httpx.get(url, timeout=5.0).text)
    return next(sample.value for family in families for sample in family.samples if sample.name == name)


def pytest_configure(config: pytest.Config) -> None:
    """One throwaway Postgres per run; each Stack gets its own database inside it.

    Provisioning goes through psql inside the container, so the harness stays free of any
    database driver or control_plane import. The TCP probe matters: initdb runs a throwaway
    socket-only server that would answer pg_isready.
    """
    if hasattr(config, "workerinput") or PG_ADMIN_ENV in os.environ:
        return
    container = (
        DockerContainer(PG_IMAGE)
        .with_env("POSTGRES_USER", "test")
        .with_env("POSTGRES_PASSWORD", "test")
        .with_env("POSTGRES_DB", "postgres")
        .with_command(PG_COMMAND)
        .with_exposed_ports(5432)
        .with_tmpfs_mount("/var/lib/postgresql/data")
    )
    container.start()
    ready = lambda: container.exec(["psql", "-h", "127.0.0.1", "-U", "test", "-d", "postgres", "-c", "SELECT 1"]).exit_code == 0  # noqa: E731
    assert _poll(ready, READY_TIMEOUT), "test postgres did not come up"
    _pg["container"] = container
    host = container.get_container_host_ip()
    port = str(container.get_exposed_port(5432))
    os.environ[PG_ADMIN_ENV] = f"postgresql://test:test@{host}:{port}/postgres"


def pytest_unconfigure(config: pytest.Config) -> None:
    container = _pg.pop("container", None)
    if isinstance(container, DockerContainer):
        container.stop()


def _create_database(name: str) -> str:
    admin_url = os.environ[PG_ADMIN_ENV].replace("postgresql+asyncpg://", "postgresql://")

    async def create() -> None:
        connection = await asyncpg.connect(admin_url)
        try:
            await connection.execute(f'CREATE DATABASE "{name}"')
        finally:
            await connection.close()

    asyncio.run(create())
    return admin_url.replace("postgresql://", "postgresql+asyncpg://").rsplit("/", 1)[0] + f"/{name}"


def _bin(name: str) -> str:
    if name == "airmux" and (candidate := os.environ.get("AIRMUX_INSTALL_BIN")):
        return candidate
    path = shutil.which(name)
    if path is None:
        pytest.skip(f"{name} console script not on PATH; run `uv sync --all-packages` first")
    return path


def _payload(response: httpx.Response) -> dict:
    """The data out of one envelope, with the status checked; the harness speaks the public API only."""
    response.raise_for_status()
    return response.json()["data"]


def _poll(predicate: Callable[[], bool], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.2)
    return False


class _StubHandler(BaseHTTPRequestHandler):
    """A stand-in OpenAI-compatible upstream: fixed reply and usage, no dependencies.

    A request with stream true gets a slow SSE stream, unhurried enough that a client can
    disconnect mid-way; the disconnect scenario's cancellation accounting depends on that pace.
    """

    STREAM_CHUNKS = 30
    STREAM_DELAY_S = 0.05

    def do_POST(self) -> None:
        server = self.server
        assert isinstance(server, _StubServer)
        server.record_request()
        if self.headers.get("authorization") != f"Bearer {STUB_API_KEY}":
            body = json.dumps({"error": {"code": "invalid_api_key", "message": "invalid provider credential"}}).encode()
            self.send_response(401)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        request = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
        messages = request.get("messages")
        message = messages[-1] if isinstance(messages, list) and messages and isinstance(messages[-1], dict) else {}
        prompt = message.get("content")
        if prompt == "fallback-primary-unavailable" and request.get("model") == MODEL:
            body = json.dumps({"error": {"message": "primary unavailable"}}).encode("utf-8")
            self.send_response(503)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if prompt == "rate-limited":
            body = json.dumps({"error": {"code": "rate_limit_exceeded", "message": "slow down"}}).encode("utf-8")
            self.send_response(429)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if request.get("stream"):
            self._stream_response()
            return
        if prompt == "malformed-buffered":
            body = b"{}"
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        content = json.dumps(request) if request.get("model") == ECHO_MODEL else "ok"
        body = json.dumps(
            {
                "id": "cmpl-stub",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 3,
                    "total_tokens": 14,
                    "prompt_tokens_details": {"cached_tokens": 4},
                },
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream_response(self) -> None:
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            for i in range(self.STREAM_CHUNKS):
                event = {"id": "cmpl-stub", "choices": [{"index": 0, "delta": {"content": f"tick{i} "}, "finish_reason": None}]}
                self.wfile.write(b"data: " + json.dumps(event).encode() + b"\n\n")
                self.wfile.flush()
                time.sleep(self.STREAM_DELAY_S)
            finish = {"id": "cmpl-stub", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            usage = {"id": "cmpl-stub", "choices": [], "usage": {"prompt_tokens": 11, "completion_tokens": 60, "total_tokens": 71}}
            for event in (finish, usage):
                self.wfile.write(b"data: " + json.dumps(event).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        server = self.server
        assert isinstance(server, _StubServer)
        server.record_response(code)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 name fixed by the BaseHTTPRequestHandler override
        return


class _StubServer(ThreadingHTTPServer):
    request_queue_size = 128

    def __init__(self, address: tuple[str, int], log_path: Path) -> None:
        self.log = log_path.open("a", encoding="utf-8")
        super().__init__(address, _StubHandler)
        self._request_count = 0
        self._request_lock = threading.Lock()

    def record_request(self) -> None:
        with self._request_lock:
            self._request_count += 1

    def start(self) -> None:
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def record_response(self, status: int | str) -> None:
        with self._request_lock:
            self.log.write(json.dumps({"time": time.monotonic(), "request": self._request_count, "status": status}) + "\n")
            self.log.flush()

    def server_close(self) -> None:
        super().server_close()
        self.log.close()

    @property
    def request_count(self) -> int:
        with self._request_lock:
            return self._request_count


class Stack:
    """One isolated deployment: cache dir, its own postgres database, config and three processes under a tmp cwd."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.db_url = _create_database(f"acc_{uuid4().hex[:12]}")
        self.cp_port: int | None = None
        self.dp_port: int | None = None
        self.cp_url = "http://127.0.0.1:0"
        self.dp_url = "http://127.0.0.1:0"
        self.cache_dir = tmp / ".airmux"
        self.config_path = tmp / "config.yml"
        self.caller_api_key = ""
        self.org_id = ""
        self.provisioned = False
        self.env: dict[str, str] = {}
        self.sensitive_values: tuple[str, ...] = (ADMIN_PASSWORD, STUB_API_KEY, "sk-stub", self.db_url)
        self._procs: dict[str, tuple[subprocess.Popen[bytes], TextIO]] = {}
        self._stub = _StubServer(("127.0.0.1", 0), tmp / "upstream.log")
        self.stub_port = self._stub.server_port
        self._stub.start()

    # setup ----------------------------------------------------------------

    def _provision_keys(self) -> None:
        """What has to exist before the control plane starts: the pool key and catalog file.

        The configured pool key is seeded by control-plane startup before any human account exists.
        """
        self._write_taxonomy()
        self.env = {
            **os.environ,
            "AIRMUX_CONFIG": str(self.config_path),
            "OPENAI_API_KEY": "sk-stub",
            "AIRMUX_DATAPLANE_TOKEN": f"sk-cp-{secrets.token_urlsafe(32)}",
        }

    def _bootstrap(self) -> None:
        """Provision the tenant the way an operator does, over the public surfaces only.

        The first signup claims the instance, which is what makes the rest reachable: the org, a
        workspace, the caller's inference key, and a human management key.

        The taxonomy runs in the middle rather than last, because a provider credential names a
        provider that has to exist first. The credential is what a workspace brings, so the deployment
        is not provisioned until it has one: without it every request is denied for having no key to
        spend, which is the shape of the failure this ordering exists to prevent.
        """
        with httpx.Client(base_url=self.cp_url, headers={"X-Requested-With": "XMLHttpRequest"}, timeout=10.0) as session:
            me = _payload(session.post("/api/v1/auth/signup", json={"email": ADMIN_EMAIL, "name": "Acceptance Admin", "password": ADMIN_PASSWORD}))
            assert me["instance_role"] == "owner", "the first signup should have claimed the instance"
            org = _payload(session.post("/api/v1/organizations", json={"name": ORG}))
            self.org_id = org["id"]
            _payload(session.put(f"/api/v1/organizations/{self.org_id}/users/{me['user_id']}", json={"role": "owner"}))
            workspace = _payload(session.post(f"/api/v1/organizations/{self.org_id}/workspaces", json={"name": "acceptance"}))
            caller = _payload(
                session.post(
                    f"/api/v1/organizations/{self.org_id}/workspaces/{workspace['id']}/inference-keys",
                    json={"label": "caller", "user_id": me["user_id"]},
                )
            )
            management_key = _payload(
                session.post(
                    f"/api/v1/organizations/{self.org_id}/management-keys",
                    json={"label": "acceptance", "permissions": ["usage.read"]},
                )
            )
            self._run([_bin("airmux"), "control-plane", "taxonomy", "--file", "taxonomy.yml", "--config", str(self.config_path)], self.env)
            _payload(session.post(f"/api/v1/organizations/{self.org_id}/provider-credentials", json={"provider": "stub", "value": STUB_API_KEY}))
            _payload(session.post(f"/api/v1/organizations/{self.org_id}/provider-credentials", json={"provider": "quirk", "value": STUB_API_KEY}))
            self.sensitive_values = (*self.sensitive_values, *session.cookies.values())

        secrets = {
            "AIRMUX_INFERENCE_KEY": caller["token"],
            "AIRMUX_MANAGEMENT_KEY": management_key["token"],
            "AIRMUX_DATAPLANE_TOKEN": self.env["AIRMUX_DATAPLANE_TOKEN"],
        }
        (self.tmp / ".env").write_text("".join(f"{name}={value}\n" for name, value in secrets.items()), encoding="utf-8")
        self.env = {**self.env, **secrets}
        self.caller_api_key = caller["token"]
        self.provisioned = True

    def _write_taxonomy(self) -> None:
        """The stub provider, plus a quirky one that exists to prove onboarding is config: it
        respells max_output_tokens, closes its schema, and declares the one extra param it accepts."""
        spec = {
            "providers": [
                {
                    "provider_id": "stub",
                    "kind": "openai_compatible",
                    "base_url": f"http://127.0.0.1:{self.stub_port}",
                },
                {
                    "provider_id": "quirk",
                    "kind": "openai_compatible",
                    "base_url": f"http://127.0.0.1:{self.stub_port}",
                    "param_aliases": {"max_output_tokens": "max_completion_tokens"},
                    "accepted_params": ["top_k"],
                    "params_closed": True,
                },
            ],
            "models": [
                {
                    "model_id": MODEL,
                    "provider_id": "stub",
                    "upstream_model": MODEL,
                    "input_modalities": ["text"],
                    "output_modalities": ["text"],
                },
                {
                    "model_id": "quirk",
                    "provider_id": "quirk",
                    "upstream_model": ECHO_MODEL,
                    "input_modalities": ["text"],
                    "output_modalities": ["text"],
                },
                {
                    "model_id": "no-temperature",
                    "provider_id": "stub",
                    "upstream_model": ECHO_MODEL,
                    "input_modalities": ["text"],
                    "output_modalities": ["text"],
                    "parameter_support": {"temperature": "unsupported"},
                },
            ],
        }
        (self.tmp / "taxonomy.yml").write_text(yaml.safe_dump(spec), encoding="utf-8")

    def write_config(
        self,
        *,
        poll_interval_s: int = 1,
        budget_poll_interval_s: int = 1,
        flush_interval_s: int = 1,
        outbox_kind: Literal["sqlite", "devnull"] = "sqlite",
        secrets_kind: Literal["file", "insecure_database"] = "file",
    ) -> None:
        """Write both planes against one secret store and the selected event outbox."""
        secrets_store = (
            {"kind": "file", "path": str(self.tmp / "secrets")} if secrets_kind == "file" else {"kind": "insecure_database", "url": self.db_url}
        )
        control_plane_link = {"url": self.cp_url, "management_key": "${env:AIRMUX_DATAPLANE_TOKEN}"}
        outbox_config = (
            {"kind": "devnull"}
            if outbox_kind == "devnull"
            else {
                "kind": "sqlite",
                "control_plane": dict(control_plane_link),
                "flush_interval_s": flush_interval_s,
                "cache_dir": str(self.cache_dir),
            }
        )
        cfg = {
            "control_plane": {
                "database": {"url": self.db_url},
                "bootstrap": {"token": "${env:AIRMUX_DATAPLANE_TOKEN}"},
                "secrets": secrets_store,
            },
            "data_plane": {
                "secrets": secrets_store,
                "bundle": {
                    "kind": "remote",
                    "control_plane": dict(control_plane_link),
                    "cache_dir": str(self.cache_dir),
                    "poll_interval_s": poll_interval_s,
                    "heartbeat_interval_s": 2,
                },
                "events": outbox_config,
                "budget": {
                    "kind": "control_plane",
                    "control_plane": dict(control_plane_link),
                    "poll_interval_s": budget_poll_interval_s,
                },
            },
        }
        self.config_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

    def collect_credentials(self) -> None:
        """Collect the credentials the bootstrap created in .env; a checkpoint that they all exist."""
        secrets = {k: v for k, v in dotenv_values(self.tmp / ".env").items() if v is not None}
        self.env = {**self.env, **secrets}
        token = secrets.get("AIRMUX_INFERENCE_KEY")
        assert token, "bootstrap did not create a caller api key"
        assert secrets.get("AIRMUX_MANAGEMENT_KEY"), "bootstrap did not create a management key"
        assert secrets.get("AIRMUX_DATAPLANE_TOKEN"), "bootstrap did not create a data plane token"
        self.caller_api_key = token

    # processes ------------------------------------------------------------

    def start_cp(self) -> None:
        if not self.env:
            self._provision_keys()
        self._run([_bin("airmux"), "control-plane", "migrate", "--config", str(self.config_path)], self.env)
        previous_url = self.cp_url
        self._spawn(
            "cp",
            [_bin("airmux"), "control-plane", "serve", "--host", "127.0.0.1", "--port", str(self.cp_port or 0), "--config", str(self.config_path)],
        )
        if self.cp_port is None:
            assert _poll(lambda: self._discover_port("cp"), READY_TIMEOUT), "control plane did not bind a port"
            self._replace_control_plane_url(previous_url)
        assert _poll(lambda: self._up(f"{self.cp_url}/openapi.json"), READY_TIMEOUT), "control plane did not come up"
        if not self.provisioned:
            self._bootstrap()  # a restart keeps the deployment it already provisioned

    def start_dp(self, workers: int = 1) -> None:
        cmd = [_bin("airmux"), "gateway", "serve", "--host", "127.0.0.1", "--port", str(self.dp_port or 0), "--config", str(self.config_path)]
        self._spawn("dp", [*cmd, "--workers", str(workers)])
        if self.dp_port is None:
            assert _poll(lambda: self._discover_port("dp"), READY_TIMEOUT), "data plane did not bind a port"
        assert _poll(lambda: self._responds(f"{self.dp_url}/healthz"), READY_TIMEOUT), "data plane process did not start"

    def stop(self, name: str, sig: int = signal.SIGTERM) -> None:
        proc, log = self._procs.pop(name)
        proc.send_signal(sig)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        log.close()

    def teardown(self) -> None:
        try:
            for name in list(self._procs):
                self.stop(name)
            self._stub.shutdown()
            self._stub.server_close()
        finally:
            artifacts = os.environ.get("AIRMUX_STACK_ARTIFACTS")
            if artifacts:
                secrets = (
                    *self.sensitive_values,
                    self.caller_api_key,
                    *(value for name, value in self.env.items() if name.startswith("AIRMUX_") and ("KEY" in name or "TOKEN" in name)),
                )
                retain_logs(self.tmp, Path(artifacts) / self.tmp.name, ("cp.log", "dp.log", "upstream.log", "commands.log"), secrets)

    # observation ----------------------------------------------------------

    def wait_dp_ready(self) -> None:
        assert _poll(self.model_ready, READY_TIMEOUT), "data plane never served the configured model"

    def model_ready(self, client: httpx.Client | None = None) -> bool:
        url = "/inf/v1/models" if client else f"{self.dp_url}/inf/v1/models"
        try:
            response = (client or httpx).get(url, headers={"Authorization": f"Bearer {self.caller_api_key}"}, timeout=2.0)
        except httpx.HTTPError:
            return False
        return response.status_code == 200 and any(model["id"] == MODEL for model in response.json().get("data", []))

    def request(self, content: str = "hi") -> httpx.Response:
        return httpx.post(
            f"{self.dp_url}/inf/v1/chat/completions",
            headers={"authorization": f"Bearer {self.caller_api_key}"},
            json={"model": MODEL, "messages": [{"role": "user", "content": content}]},
            timeout=10.0,
        )

    @property
    def upstream_requests(self) -> int:
        return self._stub.request_count

    def healthz(self) -> int:
        return httpx.get(f"{self.dp_url}/healthz", timeout=5.0).status_code

    def events(self) -> list[dict]:
        events: list[dict] = []
        page_query: dict[str, int | str] = {"limit": 200}
        while True:
            response = httpx.get(
                f"{self.cp_url}/api/v1/organizations/{self.org_id}/events",
                headers={"authorization": f"Bearer {self.env['AIRMUX_MANAGEMENT_KEY']}"},
                params=page_query,
                timeout=10.0,
            )
            response.raise_for_status()
            page = response.json()["data"]
            events.extend(page)
            if len(page) < 200:
                return events
            oldest = page[-1]
            page_query = {"limit": 200, "before": oldest["occurred_at"], "before_event_id": oldest["event_id"]}

    # internals ------------------------------------------------------------

    def _run(self, cmd: list[str], env: dict[str, str]) -> None:
        with (self.tmp / "commands.log").open("a", encoding="utf-8") as log:
            subprocess.run(cmd, cwd=self.tmp, env=env, check=True, stdout=log, stderr=subprocess.STDOUT)  # noqa: S603 harness runs trusted local console scripts

    def _spawn(self, name: str, cmd: list[str]) -> None:
        log = (self.tmp / f"{name}.log").open("a", encoding="utf-8")
        proc = subprocess.Popen(cmd, cwd=self.tmp, env=self.env, stdout=log, stderr=subprocess.STDOUT)  # noqa: S603 trusted local console scripts
        self._procs[name] = (proc, log)

    def _discover_port(self, name: Literal["cp", "dp"]) -> bool:
        proc, _ = self._procs[name]
        assert proc.poll() is None, (self.tmp / f"{name}.log").read_text(encoding="utf-8")
        port = uvicorn_port(self.tmp / f"{name}.log")
        if port is None:
            return False
        if name == "cp":
            self.cp_port = port
            self.cp_url = f"http://127.0.0.1:{port}"
        else:
            self.dp_port = port
            self.dp_url = f"http://127.0.0.1:{port}"
        return True

    def _replace_control_plane_url(self, previous_url: str) -> None:
        configuration = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        for section in (
            configuration["data_plane"]["bundle"],
            configuration["data_plane"]["events"],
            configuration["data_plane"]["budget"],
        ):
            control_plane = section.get("control_plane")
            if control_plane and control_plane["url"] == previous_url:
                control_plane["url"] = self.cp_url
        self.config_path.write_text(yaml.safe_dump(configuration), encoding="utf-8")

    @staticmethod
    def _up(url: str) -> bool:
        try:
            return httpx.get(url, timeout=2.0).status_code == 200
        except httpx.HTTPError:
            return False

    @staticmethod
    def _responds(url: str) -> bool:
        try:
            httpx.get(url, timeout=2.0)
        except httpx.HTTPError:
            return False
        return True


@pytest.fixture
def stack(tmp_path: Path) -> Iterator[Stack]:
    s = Stack(tmp_path)
    try:
        yield s
    finally:
        s.teardown()
