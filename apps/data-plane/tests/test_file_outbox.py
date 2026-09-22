from __future__ import annotations

import asyncio
import fcntl
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from pydantic import TypeAdapter, ValidationError

from airmux_runtime.config import ConfigContext
from contract import RoutedUsageEventV1, TokenUsageSource, UsageEvent, uuid7
from data_plane.config import Config, FileOutboxConfig
from data_plane.metrics import DataPlaneMetrics
from data_plane.outbox import EventOutbox, FileOutbox, build_outbox

if TYPE_CHECKING:
    from pathlib import Path


def event_of(index: int) -> RoutedUsageEventV1:
    return RoutedUsageEventV1(
        event_id=uuid7(),
        request_id=uuid7(),
        request_started_at=datetime.now(tz=UTC),
        attempt_started_at=datetime.now(tz=UTC),
        occurred_at=datetime.now(tz=UTC),
        org_id=uuid7(),
        workspace_id=uuid7(),
        key_id="local-0",
        user_id=uuid7(),
        requested_model_id=f"model-{index}",
        requested_capabilities=frozenset(),
        model_id=f"model-{index}",
        provider_id="stub",
        bundle_id=uuid7(),
        input_tokens=11,
        token_usage_source=TokenUsageSource.PROVIDER,
        output_tokens=3,
        max_output_tokens=128,
        cost_usd="0.000037",
        cost_input_usd="0.000037",
        latency_ms=1,
        status="ok",
        stream=False,
        credential_id=uuid7(),
        credential_scope="platform",
    )


def record(outbox: EventOutbox, event: UsageEvent) -> None:
    with outbox.reserve() as reservation:
        reservation.record(event)


def write_events(path: Path, start: int, count: int) -> None:
    outbox = FileOutbox(FileOutboxConfig(path=path), DataPlaneMetrics())
    try:
        for index in range(start, start + count):
            record(outbox, event_of(index))
    finally:
        asyncio.run(outbox.close())


def read_events(path: Path) -> list[UsageEvent]:
    return TypeAdapter(list[UsageEvent]).validate_json("[" + ",".join(path.read_text().splitlines()) + "]", strict=True)


async def test_file_events_flush_asynchronously_and_append_after_reopening(tmp_path, http_client):
    path = tmp_path / "nested/events.jsonl"
    events = [event_of(0), event_of(1)]
    outbox = build_outbox(FileOutboxConfig(path=path), http_client, DataPlaneMetrics())
    try:
        record(outbox, events[0])
    finally:
        await outbox.close()
    assert read_events(path) == events[:1]

    reopened = FileOutbox(FileOutboxConfig(path=path), DataPlaneMetrics())
    try:
        record(reopened, events[1])
    finally:
        await reopened.close()
    assert read_events(path) == events
    assert path.stat().st_mode & 0o777 == 0o600


def test_file_events_do_not_wait_for_advisory_locks(tmp_path):
    path = tmp_path / "events.jsonl"
    outbox = FileOutbox(FileOutboxConfig(path=path), DataPlaneMetrics())
    event = event_of(0)
    executor = ThreadPoolExecutor(max_workers=1)
    with path.open("a") as event_file:
        fcntl.flock(event_file.fileno(), fcntl.LOCK_EX)
        try:
            record(outbox, event)
            close = executor.submit(asyncio.run, outbox.close())
            close.result(timeout=1)
        finally:
            fcntl.flock(event_file.fileno(), fcntl.LOCK_UN)
            executor.shutdown()
    assert read_events(path) == [event]


def test_file_events_from_concurrent_threads_remain_complete(tmp_path):
    path = tmp_path / "events.jsonl"
    outbox = FileOutbox(FileOutboxConfig(path=path), DataPlaneMetrics())
    events = [event_of(index) for index in range(100)]
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(lambda event: record(outbox, event), events))
    finally:
        asyncio.run(outbox.close())
    assert {event.event_id for event in read_events(path)} == {event.event_id for event in events}
    assert len(read_events(path)) == len(events)


def test_file_events_from_concurrent_processes_remain_complete(tmp_path):
    path = tmp_path / "events.jsonl"
    context = multiprocessing.get_context("spawn")
    processes = [context.Process(target=write_events, args=(path, worker * 50, 50)) for worker in range(3)]
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=20)
            assert process.exitcode == 0
        events = read_events(path)
        assert len(events) == 150
        assert len({event.event_id for event in events}) == 150
        assert {event.model_id for event in events} == {f"model-{index}" for index in range(150)}
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)


def test_file_event_path_resolves_from_the_configuration_directory(tmp_path):
    config = Config.model_validate(
        {"bundle": {"kind": "local", "path": "bundle.yml"}, "events": {"kind": "file", "path": "logs/events.jsonl"}},
        context=ConfigContext(base_dir=tmp_path),
    )
    assert isinstance(config.events, FileOutboxConfig)
    assert config.events.path == tmp_path / "logs/events.jsonl"


@pytest.mark.parametrize("events", [{"kind": "file"}, {"kind": "file", "path": "events.jsonl", "flush_interval_s": 1}, {"kind": "unknown"}])
def test_file_event_configuration_rejects_invalid_states(events):
    with pytest.raises(ValidationError):
        Config.model_validate({"bundle": {"kind": "local", "path": "bundle.yml"}, "events": events})
