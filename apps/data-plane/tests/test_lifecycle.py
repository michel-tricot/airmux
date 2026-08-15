from __future__ import annotations

import asyncio
import threading

import pytest
from starlette.testclient import TestClient

import data_plane.app as app_module
from data_plane.app import create_app
from data_plane.bundle import BundleSource, LocalBundleConfig
from data_plane.config import Config


class FailingSource(BundleSource):
    def __init__(self) -> None:
        self.failed = threading.Event()
        self.stopped = threading.Event()

    async def _fail(self) -> None:
        await asyncio.sleep(0.01)
        self.failed.set()
        message = "bundle worker failed"
        raise RuntimeError(message)

    async def _wait(self) -> None:
        try:
            await asyncio.Future()
        finally:
            self.stopped.set()

    def start(self, task_group: asyncio.TaskGroup, /) -> tuple[asyncio.Task[None], ...]:
        return task_group.create_task(self._fail()), task_group.create_task(self._wait())


def test_unexpected_worker_failure_stops_the_app_and_cancels_its_siblings(tmp_path, monkeypatch):
    source = FailingSource()
    monkeypatch.setattr(app_module, "build_bundle_source", lambda *_args: source)
    app = create_app(Config(bundle=LocalBundleConfig(kind="local", path=tmp_path / "bundle.yml")))

    with pytest.RaisesGroup(pytest.RaisesExc(RuntimeError, match="bundle worker failed")), TestClient(app):
        assert source.failed.wait(1)

    assert source.stopped.is_set()
