from __future__ import annotations

import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from pydantic import TypeAdapter, ValidationError

from contract import RoutedUsageEventV1, UsageEvent, uuid7
from contract.config import ConfigContext
from data_plane.config import Config, FileOutboxConfig
from data_plane.outbox import FileOutbox, build_outbox

if TYPE_CHECKING:
    from pathlib import Path


def event_of(index: int) -> RoutedUsageEventV1:
    return RoutedUsageEventV1(
        event_id=uuid7(),
        request_id=uuid7(),
        occurred_at=datetime.now(tz=UTC),
        org_id=uuid7(),
        workspace_id=uuid7(),
        key_id="local-0",
        model_id=f"model-{index}",
        provider_id="stub",
        bundle_id=uuid7(),
        input_tokens=11,
        output_tokens=3,
        cost_usd="0.000037",
        cost_input_usd="0.000037",
        latency_ms=1,
        status="ok",
        stream=False,
        credential_id=uuid7(),
        credential_scope="platform",
    )


def write_events(path: Path, start: int, count: int) -> None:
    outbox = FileOutbox(FileOutboxConfig(path=path))
    try:
        for index in range(start, start + count):
            outbox.record(event_of(index))
    finally:
        outbox.close()


def read_events(path: Path) -> list[UsageEvent]:
    return TypeAdapter(list[UsageEvent]).validate_json("[" + ",".join(path.read_text().splitlines()) + "]", strict=True)


def test_file_events_are_visible_before_close_and_append_after_reopening(tmp_path, http_client):
    path = tmp_path / "nested/events.jsonl"
    events = [event_of(0), event_of(1)]
    outbox = build_outbox(FileOutboxConfig(path=path), http_client)
    try:
        outbox.record(events[0])
        assert read_events(path) == events[:1]
        assert outbox.stats().pending == 0
    finally:
        outbox.close()
    reopened = FileOutbox(FileOutboxConfig(path=path))
    try:
        reopened.record(events[1])
        assert read_events(path) == events
    finally:
        reopened.close()
    assert path.stat().st_mode & 0o777 == 0o600


def test_file_events_from_concurrent_threads_remain_complete(tmp_path):
    path = tmp_path / "events.jsonl"
    outbox = FileOutbox(FileOutboxConfig(path=path))
    events = [event_of(index) for index in range(100)]
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(outbox.record, events))
        assert {event.event_id for event in read_events(path)} == {event.event_id for event in events}
        assert len(read_events(path)) == len(events)
    finally:
        outbox.close()


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
