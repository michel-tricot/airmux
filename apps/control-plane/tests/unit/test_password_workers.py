from __future__ import annotations

import asyncio
import gc
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


async def test_cancelled_queued_password_work_keeps_its_admission_slot(monkeypatch):
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def hash_password(password: str) -> str:
        loop.call_soon_threadsafe(started.set)
        assert release.wait(5)
        return password

    monkeypatch.setattr("control_plane.passwords.hash_password", hash_password)
    workers = PasswordWorkers(workers=1, queue=1)
    first = asyncio.create_task(workers.hash("first"))
    third = None
    try:
        async with asyncio.timeout(2):
            await started.wait()
        second = asyncio.create_task(workers.hash("second"))
        await asyncio.sleep(0)
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        await asyncio.sleep(0)
        third = asyncio.create_task(workers.hash("third"))
        await asyncio.sleep(0)
        assert third.done(), "Cancelled queued work must not admit another password operation"
        with pytest.raises(ThrottledError):
            await third
    finally:
        release.set()
        workers.close()
        await first
        if third is not None:
            await asyncio.gather(third, return_exceptions=True)


async def test_cancelled_password_failure_is_observed_and_capacity_recovers(monkeypatch):
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    failures = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: failures.append(context))

    def hash_password(password: str) -> str:
        if password == "fail":
            loop.call_soon_threadsafe(started.set)
            assert release.wait(5)
            raise RuntimeError
        return password

    monkeypatch.setattr("control_plane.passwords.hash_password", hash_password)
    workers = PasswordWorkers(workers=1, queue=1)
    first = asyncio.create_task(workers.hash("fail"))
    try:
        async with asyncio.timeout(2):
            await started.wait()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        release.set()
        assert await workers.hash("recovered") == "recovered"
        await asyncio.sleep(0)
        gc.collect()
        await asyncio.sleep(0)
        assert failures == []
    finally:
        release.set()
        workers.close()
        loop.set_exception_handler(previous_handler)
