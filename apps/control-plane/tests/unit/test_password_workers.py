from __future__ import annotations

import asyncio
import threading

import pytest

from control_plane.passwords import PasswordWorkers
from control_plane.throttling import ThrottledError


async def test_password_workers_bound_work_and_keep_event_loop_responsive(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    started = asyncio.Event()
    loop = asyncio.get_running_loop()

    def hash_password(password: str) -> str:
        entered.set()
        loop.call_soon_threadsafe(started.set)
        assert release.wait(5)
        return password

    monkeypatch.setattr("control_plane.passwords.hash_password", hash_password)
    workers = PasswordWorkers(workers=1, queue=0)
    first = asyncio.create_task(workers.hash("first"))
    try:
        async with asyncio.timeout(2):
            await started.wait()
        with pytest.raises(ThrottledError):
            await workers.hash("second")
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        with pytest.raises(ThrottledError):
            await workers.hash("third")
    finally:
        release.set()
        workers.close()


async def test_password_workers_hash_and_verify():
    workers = PasswordWorkers(workers=1, queue=1)
    try:
        password_hash = await workers.hash("correct-password")
        assert password_hash != "correct-password"
        assert await workers.verify(password_hash, "correct-password")
        assert not await workers.verify(password_hash, "incorrect-password")
    finally:
        workers.close()
