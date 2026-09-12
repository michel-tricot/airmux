from __future__ import annotations

import asyncio
import contextvars
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TYPE_CHECKING

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from control_plane.throttling import Denied, ThrottledError

if TYPE_CHECKING:
    from collections.abc import Callable

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, candidate: str) -> bool:
    try:
        _hasher.verify(stored_hash, candidate)
    except (VerifyMismatchError, InvalidHashError):
        return False
    return True


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)


DUMMY_HASH = _hasher.hash("dummy")


class PasswordWorkers:
    def __init__(self, *, workers: int, queue: int) -> None:
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="password")
        self._capacity = threading.BoundedSemaphore(workers + queue)

    async def _run[T](self, function: Callable[..., T], *args: str) -> T:
        def compute() -> T:
            return contextvars.Context().run(function, *args)

        if not self._capacity.acquire(blocking=False):
            raise ThrottledError(Denied(retry_after=1, reason="capacity"))
        try:
            future = self._executor.submit(compute)
        except BaseException:
            self._capacity.release()
            raise
        future.add_done_callback(self._release)
        return await asyncio.wrap_future(future)

    def _release(self, _future: Future) -> None:
        self._capacity.release()

    async def hash(self, password: str) -> str:
        return await self._run(hash_password, password)

    async def verify(self, stored_hash: str, candidate: str) -> bool:
        return await self._run(verify_password, stored_hash, candidate)

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)
