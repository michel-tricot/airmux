from __future__ import annotations

import os
from typing import TYPE_CHECKING
from uuid import uuid4

from contract import SignedBundle

if TYPE_CHECKING:
    from pathlib import Path


class CacheDirLockedError(Exception):
    def __init__(self, cache_dir: Path, pid: int) -> None:
        super().__init__(f"cache dir {cache_dir} is already served by live process {pid}; run one data plane per cache dir")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire_cache_lock(cache_dir: Path) -> None:
    """The buffer and cache formats assume a single writer; refuse to share the dir with a live process."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    lock = cache_dir / "dp.lock"
    for _ in range(2):
        try:
            with lock.open("x", encoding="utf-8") as f:
                f.write(str(os.getpid()))
        except FileExistsError:
            raw = lock.read_text(encoding="utf-8").strip()
            pid = int(raw) if raw.isdigit() else 0
            if pid == os.getpid():
                return
            if pid and _alive(pid):
                raise CacheDirLockedError(cache_dir, pid) from None
            lock.unlink(missing_ok=True)
        else:
            return
    raise CacheDirLockedError(cache_dir, 0)


def release_cache_lock(cache_dir: Path) -> None:
    lock = cache_dir / "dp.lock"
    if lock.exists() and lock.read_text(encoding="utf-8").strip() == str(os.getpid()):
        lock.unlink()


def atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def instance_id(cache_dir: Path) -> str:
    """A stable id per data plane, persisted beside the lock so a restart keeps its identity."""
    path = cache_dir / "instance_id"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    new_id = uuid4().hex
    path.write_text(new_id, encoding="utf-8")
    return new_id


def read_cached_bundle(cache_dir: Path) -> SignedBundle | None:
    path = cache_dir / "bundle.json"
    if not path.exists():
        return None
    return SignedBundle.model_validate_json(path.read_text(encoding="utf-8"))


def write_cached_bundle(cache_dir: Path, signed: SignedBundle) -> None:
    atomic_write_text(cache_dir / "bundle.json", signed.model_dump_json(indent=2))
