from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import httpx2
import pytest
from starlette.testclient import TestClient

import data_plane.app as app_module
from contract import DeniedUsageEventV1, TokenUsageSource, uuid7
from data_plane.app import create_app
from data_plane.bundle import BundleSource, LocalBundleConfig
from data_plane.config import Config, FileOutboxConfig
from data_plane.metrics import DataPlaneMetrics
from data_plane.outbox import FileOutbox

if TYPE_CHECKING:
    from starlette.types import ASGIApp

    from data_plane.bundle import BundleConfig, BundleHolder


class FailingSource(BundleSource):
    def __init__(self, delay_s: float = 0.01) -> None:
        self.delay_s = delay_s
        self.failed = threading.Event()
        self.stopped = threading.Event()

    async def _fail(self) -> None:
        await asyncio.sleep(self.delay_s)
        self.failed.set()
        message = "bundle worker failed"
        raise RuntimeError(message)

    async def _wait(self) -> None:
        try:
            await asyncio.Future()
        finally:
            self.stopped.set()

    def start(self, task_group: asyncio.TaskGroup, /) -> tuple[asyncio.Task[None], ...]:
        return task_group.create_task(self._fail(), name="failing bundle worker"), task_group.create_task(self._wait(), name="waiting bundle worker")


def test_unexpected_worker_failure_stops_the_app_and_cancels_its_siblings(tmp_path, monkeypatch):
    source = FailingSource()
    terminated = threading.Event()
    monkeypatch.setattr(app_module, "build_bundle_source", lambda *_args: source)
    monkeypatch.setattr(app_module, "_terminate_process", terminated.set, raising=False)
    app = create_app(Config(bundle=LocalBundleConfig(kind="local", path=tmp_path / "bundle.yml")))

    with pytest.RaisesGroup(pytest.RaisesExc(RuntimeError, match="bundle worker failed")), TestClient(app):
        assert source.failed.wait(1)

    assert source.stopped.is_set()
    assert terminated.is_set()


def test_storage_worker_failure_stops_the_app(tmp_path, monkeypatch):
    source = FailingSource(delay_s=60)
    outbox = FileOutbox(FileOutboxConfig(path=tmp_path / "events.jsonl"), DataPlaneMetrics())
    failed = threading.Event()
    terminated = threading.Event()

    def fail(_events):
        failed.set()
        message = "event storage failed"
        raise OSError(message)

    monkeypatch.setattr(outbox, "_persist", fail)
    monkeypatch.setattr(app_module, "build_bundle_source", lambda *_args: source)
    monkeypatch.setattr(app_module, "build_outbox", lambda *_args: outbox)
    monkeypatch.setattr(app_module, "_terminate_process", terminated.set)
    app = create_app(Config(bundle=LocalBundleConfig(kind="local", path=tmp_path / "bundle.yml")))

    def run() -> None:
        with TestClient(app):
            with outbox.reserve() as reservation:
                reservation.record(
                    DeniedUsageEventV1(
                        event_id=uuid7(),
                        request_id=uuid7(),
                        request_started_at=datetime.now(tz=UTC),
                        occurred_at=datetime.now(tz=UTC),
                        org_id=uuid7(),
                        workspace_id=uuid7(),
                        key_id="test",
                        request_source="inference_key",
                        user_id=uuid7(),
                        requested_model_id="test",
                        requested_capabilities=frozenset(),
                        model_id="test",
                        provider_id="",
                        bundle_id=uuid7(),
                        input_tokens=0,
                        token_usage_source=TokenUsageSource.NOT_APPLICABLE,
                        output_tokens=0,
                        max_output_tokens=None,
                        cost_usd="0",
                        latency_ms=0,
                        status="denied",
                        stream=False,
                    )
                )
            assert failed.wait(1)
            assert terminated.wait(1)

    with pytest.raises(OSError, match="event storage failed"):
        run()


def failing_app() -> ASGIApp:
    source = FailingSource(delay_s=2.0)

    def build_source(
        config: BundleConfig,
        holder: BundleHolder,
        http_client: httpx2.AsyncClient,
    ) -> BundleSource:
        return source

    app_module.__dict__["build_bundle_source"] = build_source
    return create_app(Config(bundle=LocalBundleConfig(kind="local", path=Path("unused.yml"))))


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def test_unexpected_worker_failure_terminates_a_uvicorn_process():
    port = _free_port()
    repo = Path(__file__).resolve().parents[3]
    python_path = [repo / "apps/data-plane/src", repo / "lib/contract/src", repo / "lib/api-models/src"]
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join([*(str(path) for path in python_path), os.environ.get("PYTHONPATH", "")])}
    process = subprocess.Popen(  # noqa: S603 trusted interpreter and local test application
        [
            sys.executable,
            "-m",
            "uvicorn",
            "test_lifecycle:failing_app",
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
    served = False
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and process.poll() is None:
            try:
                served = httpx2.get(f"http://127.0.0.1:{port}/healthz", timeout=0.2).status_code == 200
            except httpx2.HTTPError:
                time.sleep(0.02)
                continue
            if served:
                break
        returncode = process.wait(timeout=5)
        output = process.communicate(timeout=1)[0]
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)

    assert served, output
    assert returncode != 0, output
