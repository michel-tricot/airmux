from __future__ import annotations

import os

import pytest

from data_plane.cache import CacheDirLockedError, acquire_cache_lock, release_cache_lock


def test_acquire_release_roundtrip(tmp_path):
    acquire_cache_lock(tmp_path)
    assert (tmp_path / "dp.lock").read_text() == str(os.getpid())
    acquire_cache_lock(tmp_path)
    release_cache_lock(tmp_path)
    assert not (tmp_path / "dp.lock").exists()


def test_live_foreign_process_blocks(tmp_path, monkeypatch):
    (tmp_path / "dp.lock").write_text("12345")
    monkeypatch.setattr("data_plane.cache._alive", lambda pid: True)
    with pytest.raises(CacheDirLockedError):
        acquire_cache_lock(tmp_path)


def test_stale_lock_is_taken_over(tmp_path, monkeypatch):
    (tmp_path / "dp.lock").write_text("12345")
    monkeypatch.setattr("data_plane.cache._alive", lambda pid: False)
    acquire_cache_lock(tmp_path)
    assert (tmp_path / "dp.lock").read_text() == str(os.getpid())
    release_cache_lock(tmp_path)


def test_garbage_lock_is_taken_over(tmp_path):
    (tmp_path / "dp.lock").write_text("not-a-pid")
    acquire_cache_lock(tmp_path)
    assert (tmp_path / "dp.lock").read_text() == str(os.getpid())
    release_cache_lock(tmp_path)
