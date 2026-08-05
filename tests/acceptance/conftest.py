"""Black-box acceptance harness: real control plane, data plane and a stub upstream.

Everything is driven through the shipped console scripts and public HTTP surfaces, in an
isolated working directory. Nothing here imports control_plane or data_plane; if a test can
only be written by reaching into internals, that is a gap in the product, not the test.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

import httpx
import pytest
import yaml
from dotenv import dotenv_values

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

ORG = "org-acc"
MODEL = "echo"
READY_TIMEOUT = 30.0


def _bin(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        pytest.skip(f"{name} console script not on PATH; run `uv sync --all-packages` first")
    return path


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _poll(predicate: Callable[[], bool], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.2)
    return False


class _StubHandler(BaseHTTPRequestHandler):
    """A stand-in OpenAI-compatible upstream: fixed reply and usage, no dependencies."""

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("content-length", 0)))
        body = json.dumps(
            {
                "id": "cmpl-stub",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:  # keep the stub silent
        return


class Stack:
    """One isolated deployment: cache dir, sqlite db, config and three processes under a tmp cwd."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.cp_port = _free_port()
        self.dp_port = _free_port()
        self.stub_port = _free_port()
        self.cp_url = f"http://127.0.0.1:{self.cp_port}"
        self.dp_url = f"http://127.0.0.1:{self.dp_port}"
        self.cache_dir = tmp / ".airllm"
        self.config_path = tmp / "config.yml"
        self.caller_token = ""
        self._procs: dict[str, tuple[subprocess.Popen[bytes], object]] = {}
        self._stub = ThreadingHTTPServer(("127.0.0.1", self.stub_port), _StubHandler)
        threading.Thread(target=self._stub.serve_forever, daemon=True).start()
        self._init_secrets()

    # setup ----------------------------------------------------------------

    def _init_secrets(self) -> None:
        base = {**os.environ, "GW_CONFIG": str(self.config_path)}
        self._run([_bin("airllm"), "init", "--control-plane-url", self.cp_url, "--cache-dir", str(self.cache_dir)], base)
        self._run([_bin("control-plane"), "mint-root-token", "--config", str(self.config_path)], base)
        self._write_bootstrap_spec()
        secrets = {k: v for k, v in dotenv_values(self.tmp / ".env").items() if v is not None}
        self.env = {**os.environ, **secrets, "GW_CONFIG": str(self.config_path), "OPENAI_API_KEY": "sk-stub"}

    def _write_bootstrap_spec(self) -> None:
        spec = {
            "org": ORG,
            "providers": [
                {
                    "provider_id": "stub",
                    "kind": "openai_compatible",
                    "base_url": f"http://127.0.0.1:{self.stub_port}",
                    "credential_ref": "env:OPENAI_API_KEY",
                }
            ],
            "models": [{"model_id": MODEL, "provider_id": "stub", "upstream_model": MODEL}],
            "keys": [{"allowed_models": ["*"]}],
        }
        (self.tmp / "bootstrap.yml").write_text(yaml.safe_dump(spec), encoding="utf-8")

    def write_config(
        self,
        *,
        staleness_bound_hours: float = 24,
        staleness_policy: str = "serve_and_warn",
        poll_interval_s: int = 1,
        flush_interval_s: int = 1,
        backend: str = "sqlite",
    ) -> None:
        cfg = {
            "control_plane": {
                "database": {"url": "sqlite+aiosqlite:///airllm.db"},
                "auth": {"token_signing_key": "env:GW_TOKEN_SIGNING_KEY"},
                "bundle": {"signing_key": "env:GW_BUNDLE_SIGNING_KEY", "staleness_bound_hours": staleness_bound_hours},
            },
            "data_plane": {
                "control_plane": {"url": self.cp_url, "token": "env:GW_DP_TOKEN", "heartbeat_interval_s": 2},
                "bundle": {
                    "public_key": "env:GW_BUNDLE_PUBLIC_KEY",
                    "org": ORG,
                    "cache_dir": str(self.cache_dir),
                    "staleness_policy": staleness_policy,
                    "poll_interval_s": poll_interval_s,
                },
                "auth": {"token_public_key": "env:GW_TOKEN_PUBLIC_KEY"},
                "events": {"flush_interval_s": flush_interval_s, "backend": backend},
            },
        }
        self.config_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

    def bootstrap(self) -> None:
        """Collect the tokens the control plane minted when it auto-bootstrapped on first start."""
        secrets = {k: v for k, v in dotenv_values(self.tmp / ".env").items() if v is not None}
        self.env = {**self.env, **secrets}
        token = secrets.get("AIRLLM_TOKEN")
        assert token, "control plane did not auto-bootstrap a caller token"
        assert secrets.get("GW_ORG_TOKEN"), "control plane did not auto-bootstrap an org token"
        assert secrets.get("GW_DP_TOKEN"), "control plane did not auto-bootstrap a data plane token"
        self.caller_token = token

    # processes ------------------------------------------------------------

    def start_cp(self) -> None:
        self._run([_bin("control-plane"), "migrate", "--config", str(self.config_path)], self.env)
        self._spawn("cp", [_bin("control-plane"), "serve", "--host", "127.0.0.1", "--port", str(self.cp_port), "--config", str(self.config_path)])
        assert _poll(lambda: self._up(f"{self.cp_url}/openapi.json"), READY_TIMEOUT), "control plane did not come up"

    def start_dp(self, workers: int = 1) -> None:
        cmd = [_bin("data-plane"), "--host", "127.0.0.1", "--port", str(self.dp_port), "--config", str(self.config_path), "--workers", str(workers)]
        self._spawn("dp", cmd)
        assert _poll(lambda: self._responds(f"{self.dp_url}/readyz"), READY_TIMEOUT), "data plane process did not start"

    def stop(self, name: str, sig: int = signal.SIGTERM) -> None:
        proc, log = self._procs.pop(name)
        proc.send_signal(sig)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        log.close()  # type: ignore[attr-defined]

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
            f"{self.cp_url}/org/events",
            headers={"authorization": f"Bearer {self.env['GW_ORG_TOKEN']}"},
            params={"limit": 1000},
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json()

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
