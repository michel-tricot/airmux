"""Black-box acceptance harness: real control plane, data plane and a stub upstream.

Everything is driven through the shipped console scripts and public HTTP surfaces, in an
isolated working directory. Nothing here imports control_plane or data_plane; if a test can
only be written by reaching into internals, that is a gap in the product, not the test.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import socket
import statistics
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, TextIO
from uuid import uuid4

import httpx
import pytest
import yaml
from dotenv import dotenv_values
from rich import box
from rich.console import Console
from rich.table import Table
from testcontainers.core.container import DockerContainer

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

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


def pytest_configure(config: pytest.Config) -> None:
    """One throwaway Postgres per run; each Stack gets its own database inside it.

    Provisioning goes through psql inside the container, so the harness stays free of any
    database driver or control_plane import. The TCP probe matters: initdb runs a throwaway
    socket-only server that would answer pg_isready.
    """
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
    _pg["host"] = container.get_container_host_ip()
    _pg["port"] = str(container.get_exposed_port(5432))


def pytest_unconfigure(config: pytest.Config) -> None:
    container = _pg.pop("container", None)
    if isinstance(container, DockerContainer):
        container.stop()


def _create_database(name: str) -> str:
    container = _pg["container"]
    assert isinstance(container, DockerContainer)
    result = container.exec(["psql", "-h", "127.0.0.1", "-U", "test", "-d", "postgres", "-c", f'CREATE DATABASE "{name}"'])
    assert result.exit_code == 0, result.output
    return f"postgresql+asyncpg://test:test@{_pg['host']}:{_pg['port']}/{name}"


def _bin(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        pytest.skip(f"{name} console script not on PATH; run `uv sync --all-packages` first")
    return path


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


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
        request = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
        if request.get("stream"):
            self._stream_response()
            return
        content = json.dumps(request) if request.get("model") == ECHO_MODEL else "ok"
        body = json.dumps(
            {
                "id": "cmpl-stub",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
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

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 name fixed by the BaseHTTPRequestHandler override; keeps the stub silent
        return


class Stack:
    """One isolated deployment: cache dir, its own postgres database, config and three processes under a tmp cwd."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.db_url = _create_database(f"acc_{uuid4().hex[:12]}")
        self.cp_port = _free_port()
        self.dp_port = _free_port()
        self.stub_port = _free_port()
        self.cp_url = f"http://127.0.0.1:{self.cp_port}"
        self.dp_url = f"http://127.0.0.1:{self.dp_port}"
        self.cache_dir = tmp / ".airllm"
        self.config_path = tmp / "config.yml"
        self.caller_token = ""
        self.provisioned = False
        self.env: dict[str, str] = {}
        self._procs: dict[str, tuple[subprocess.Popen[bytes], TextIO]] = {}
        self._stub = ThreadingHTTPServer(("127.0.0.1", self.stub_port), _StubHandler)
        threading.Thread(target=self._stub.serve_forever, daemon=True).start()

    # setup ----------------------------------------------------------------

    def _provision_keys(self) -> None:
        """What has to exist before the control plane starts: the bundle key pair and the catalog file.

        The signing key comes from `airllmcp keygen`, the same command an operator runs; the config
        reads both halves out of the environment.
        """
        self._write_taxonomy()
        base = {**os.environ, "GW_CONFIG": str(self.config_path)}
        key_path = self.cache_dir / "signing.key"
        self._run([_bin("airllmcp"), "keygen", "--out", str(key_path)], base)
        self.env = {
            **os.environ,
            "GW_CONFIG": str(self.config_path),
            "OPENAI_API_KEY": "sk-stub",
            "GW_BUNDLE_SIGNING_KEY": key_path.read_text(encoding="utf-8").strip(),
            "GW_BUNDLE_PUBLIC_KEY": key_path.with_suffix(".pub").read_text(encoding="utf-8").strip(),
        }

    def _bootstrap(self) -> None:
        """Provision the deployment the way an operator does, over the public surfaces only.

        The first signup claims the instance, which is what makes the rest reachable: the org, a
        workspace, the caller's inference key and the two management keys.

        The taxonomy runs in the middle rather than last, because a provider credential names a
        provider that has to exist first. The credential is what a workspace brings, so the deployment
        is not provisioned until it has one: without it every request is denied for having no key to
        spend, which is the shape of the failure this ordering exists to prevent. The explicit compile
        afterwards is what lands the catalog and the credential in the same bundle v1.
        """
        with httpx.Client(base_url=self.cp_url, headers={"X-Requested-With": "XMLHttpRequest"}, timeout=10.0) as session:
            me = _payload(session.post("/v1/auth/signup", json={"email": ADMIN_EMAIL, "name": "Acceptance Admin", "password": ADMIN_PASSWORD}))
            assert me["instance_admin"], "the first signup should have claimed the instance"
            org = _payload(session.post("/v1/orgs", json={"name": ORG}))
            scope = {"X-Org-Id": org["id"]}
            _payload(session.put(f"/v1/org/users/{me['user_id']}", headers=scope))
            workspace = _payload(session.post("/v1/org/workspaces", json={"name": "acceptance"}, headers=scope))
            caller = _payload(session.post(f"/v1/org/workspaces/{workspace['id']}/inference-keys", json={"label": "caller"}, headers=scope))
            org_key = _payload(session.post("/v1/org/management-keys", json={"label": "acceptance"}, headers=scope))
            data_plane_key = _payload(session.post("/v1/org/management-keys", json={"label": "data-plane"}, headers=scope))

            self._run([_bin("airllmcp"), "taxonomy", "--config", str(self.config_path)], self.env)
            _payload(session.post("/v1/org/provider-credentials", json={"provider": "stub", "value": STUB_API_KEY}, headers=scope))
            _payload(session.post("/v1/org/provider-credentials", json={"provider": "quirk", "value": STUB_API_KEY}, headers=scope))
            _payload(session.post("/v1/org/bundles/compile", headers=scope))

        secrets = {
            "AIRLLM_TOKEN": caller["token"],
            "GW_ORG_MGMT_TOKEN": org_key["token"],
            "GW_DATAPLANE_TOKEN": data_plane_key["token"],
            "GW_BUNDLE_SIGNING_KEY": self.env["GW_BUNDLE_SIGNING_KEY"],
            "GW_BUNDLE_PUBLIC_KEY": self.env["GW_BUNDLE_PUBLIC_KEY"],
        }
        (self.tmp / ".env").write_text("".join(f"{name}={value}\n" for name, value in secrets.items()), encoding="utf-8")
        self.env = {**self.env, **secrets}
        self.provisioned = True

    def _write_taxonomy(self) -> None:
        """The stub provider, plus a quirky one that exists to prove onboarding is config: it
        respells max_tokens, closes its schema, and declares the one extra param it accepts."""
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
                    "param_aliases": {"max_tokens": "max_completion_tokens"},
                    "accepted_params": ["top_k"],
                    "params_closed": True,
                },
            ],
            "models": [
                {"model_id": MODEL, "provider_id": "stub", "upstream_model": MODEL},
                {"model_id": "quirk", "provider_id": "quirk", "upstream_model": ECHO_MODEL},
            ],
        }
        (self.tmp / "taxonomy.yml").write_text(yaml.safe_dump(spec), encoding="utf-8")

    def write_config(
        self,
        *,
        staleness_bound_hours: float = 24,
        staleness_policy: str = "serve_and_warn",
        poll_interval_s: int = 1,
        flush_interval_s: int = 1,
        backend: str = "sqlite",
    ) -> None:
        secrets_store = {"kind": "file", "root": str(self.tmp / "secrets")}
        """Both planes name the same store, because one writes what the other reads. The file store
        is the smallest one that can hold a value the data plane will read back in another process."""
        cfg = {
            "control_plane": {
                "database": {"url": self.db_url},
                "bundle": {"signing_key": "env:GW_BUNDLE_SIGNING_KEY", "staleness_bound_hours": staleness_bound_hours},
                "secrets": secrets_store,
            },
            "data_plane": {
                "secrets": secrets_store,
                "control_plane": {"url": self.cp_url, "token": "env:GW_DATAPLANE_TOKEN", "heartbeat_interval_s": 2},
                "bundle": {
                    "kind": "remote",
                    "verify_key": "env:GW_BUNDLE_PUBLIC_KEY",
                    "cache_dir": str(self.cache_dir),
                    "staleness_policy": staleness_policy,
                    "poll_interval_s": poll_interval_s,
                },
                "events": {"flush_interval_s": flush_interval_s, "backend": backend, "cache_dir": str(self.cache_dir)},
            },
        }
        self.config_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

    def collect_tokens(self) -> None:
        """Collect the tokens the bootstrap minted into .env; a checkpoint that they all exist."""
        secrets = {k: v for k, v in dotenv_values(self.tmp / ".env").items() if v is not None}
        self.env = {**self.env, **secrets}
        token = secrets.get("AIRLLM_TOKEN")
        assert token, "bootstrap did not mint a caller token"
        assert secrets.get("GW_ORG_MGMT_TOKEN"), "bootstrap did not mint an org token"
        assert secrets.get("GW_DATAPLANE_TOKEN"), "bootstrap did not mint a data plane token"
        self.caller_token = token

    # processes ------------------------------------------------------------

    def start_cp(self) -> None:
        if not self.env:
            self._provision_keys()
        self._run([_bin("airllmcp"), "migrate", "--config", str(self.config_path)], self.env)
        self._spawn("cp", [_bin("airllmcp"), "serve", "--host", "127.0.0.1", "--port", str(self.cp_port), "--config", str(self.config_path)])
        assert _poll(lambda: self._up(f"{self.cp_url}/openapi.json"), READY_TIMEOUT), "control plane did not come up"
        if not self.provisioned:
            self._bootstrap()  # a restart keeps the deployment it already provisioned

    def start_dp(self, workers: int = 1) -> None:
        cmd = [_bin("airllmdp"), "serve", "--host", "127.0.0.1", "--port", str(self.dp_port), "--config", str(self.config_path)]
        self._spawn("dp", [*cmd, "--workers", str(workers)])
        assert _poll(lambda: self._responds(f"{self.dp_url}/readyz"), READY_TIMEOUT), "data plane process did not start"

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
        for name in list(self._procs):
            self.stop(name)  # SIGTERM so a multi-worker uvicorn reaps its workers; escalates to kill if it hangs
        self._stub.shutdown()
        self._stub.server_close()

    # observation ----------------------------------------------------------

    def wait_dp_ready(self) -> None:
        assert _poll(lambda: self._up(f"{self.dp_url}/readyz"), READY_TIMEOUT), "data plane never served a bundle"

    def request(self, content: str = "hi") -> httpx.Response:
        return httpx.post(
            f"{self.dp_url}/v1/chat/completions",
            headers={"authorization": f"Bearer {self.caller_token}"},
            json={"model": MODEL, "messages": [{"role": "user", "content": content}]},
            timeout=10.0,
        )

    def readyz(self) -> int:
        return httpx.get(f"{self.dp_url}/readyz", timeout=5.0).status_code

    def events(self) -> list[dict]:
        resp = httpx.get(
            f"{self.cp_url}/v1/org/events",
            headers={"authorization": f"Bearer {self.env['GW_ORG_MGMT_TOKEN']}"},
            params={"limit": 1000},
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json()["data"]

    def dp_log_contains(self, needle: str) -> bool:
        log = self.tmp / "dp.log"
        return log.exists() and needle in log.read_text(encoding="utf-8")

    def wait_dp_log(self, needle: str) -> bool:
        return _poll(lambda: self.dp_log_contains(needle), READY_TIMEOUT)

    # internals ------------------------------------------------------------

    def _run(self, cmd: list[str], env: dict[str, str]) -> None:
        subprocess.run(cmd, cwd=self.tmp, env=env, check=True, capture_output=True, text=True)  # noqa: S603 harness runs trusted local console scripts

    def _spawn(self, name: str, cmd: list[str]) -> None:
        log = (self.tmp / f"{name}.log").open("a", encoding="utf-8")
        proc = subprocess.Popen(cmd, cwd=self.tmp, env=self.env, stdout=log, stderr=subprocess.STDOUT)  # noqa: S603 trusted local console scripts
        self._procs[name] = (proc, log)

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


# benchmark reporting ------------------------------------------------------

PERCENTILES = (50, 90, 99)


def _pct(xs: list[float], q: float) -> float:
    ordered = sorted(xs)
    rank = max(0, min(len(ordered) - 1, round(q / 100 * len(ordered)) - 1))
    return ordered[rank]


class Bench:
    """Collects named timing series (milliseconds) and prints them as one rich table.

    Every benchmark uses the `bench` fixture so they all warm up, sample and report the same
    way. Measure a cost as a difference against a baseline (see benchmarks/test_overhead.py);
    the table shows each series and, when a baseline and treatment are named, the
    per-percentile overhead row.
    """

    def __init__(self, capsys: pytest.CaptureFixture[str]) -> None:
        self._capsys = capsys
        self._series: dict[str, list[float]] = {}

    def measure(self, name: str, call: Callable[[], object], *, warmup: int = 20, samples: int = 200) -> None:
        times: list[float] = []
        for i in range(warmup + samples):
            start = time.perf_counter()
            resp = call()
            elapsed = (time.perf_counter() - start) * 1000
            assert getattr(resp, "status_code", 200) == 200
            if i >= warmup:
                times.append(elapsed)
        self._series[name] = times

    @staticmethod
    def percentile(xs: list[float], q: float) -> float:
        return _pct(xs, q)

    def pct(self, name: str, q: float) -> float:
        return _pct(self._series[name], q)

    def overhead(self, treatment: str, baseline: str, q: float = 50) -> float:
        return _pct(self._series[treatment], q) - _pct(self._series[baseline], q)

    def report(self, *, title: str, baseline: str | None = None, treatment: str | None = None) -> None:
        table = Table(title=title, box=box.ROUNDED, header_style="bold", title_style="bold", caption="latency in milliseconds")
        table.add_column("series", style="cyan", no_wrap=True)
        table.add_column("n", justify="right")
        for q in PERCENTILES:
            table.add_column(f"p{q}", justify="right")
        table.add_column("max", justify="right")
        table.add_column("mean", justify="right")
        for name, xs in self._series.items():
            cells = [f"{_pct(xs, q):.2f}" for q in PERCENTILES] + [f"{max(xs):.2f}", f"{statistics.fmean(xs):.2f}"]
            table.add_row(name, str(len(xs)), *cells)
        if baseline and treatment:
            base, treat = self._series[baseline], self._series[treatment]
            deltas = [f"{_pct(treat, q) - _pct(base, q):.2f}" for q in PERCENTILES] + ["", f"{statistics.fmean(treat) - statistics.fmean(base):.2f}"]
            table.add_section()
            table.add_row("overhead", "", *deltas, style="bold magenta")
        with self._capsys.disabled():
            Console().print(table)

    def table(self, *, title: str, columns: list[str], rows: list[tuple[object, ...]], caption: str = "") -> None:
        """Render arbitrary tabular results (e.g. a throughput sweep) with the same styling."""
        out = Table(title=title, box=box.ROUNDED, header_style="bold", title_style="bold", caption=caption)
        out.add_column(columns[0], style="cyan", no_wrap=True)
        for name in columns[1:]:
            out.add_column(name, justify="right")
        for row in rows:
            out.add_row(*(str(cell) for cell in row))
        with self._capsys.disabled():
            Console().print(out)


@pytest.fixture
def bench(capsys: pytest.CaptureFixture[str]) -> Bench:
    return Bench(capsys)
