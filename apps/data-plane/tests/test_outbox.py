from __future__ import annotations

import contextlib
import json
import sqlite3
import time
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import httpx2
import pytest
import respx
from conftest import make_config, make_outbox

from contract import RoutedUsageEventV1, TokenUsageSource, uuid7
from data_plane.config import SqliteOutboxConfig
from data_plane.metrics import DataPlaneMetrics
from data_plane.outbox import DevNullOutbox, EventOutbox, OutboxFullError, SqliteOutbox, build_outbox
from data_plane.outbox.queued import CAPACITY
from data_plane.outbox.sqlite import BATCH_SIZE


def make_event(request_id) -> RoutedUsageEventV1:
    return RoutedUsageEventV1(
        event_id=uuid4(),
        request_id=request_id,
        request_started_at=datetime.now(tz=UTC),
        attempt_started_at=datetime.now(tz=UTC),
        occurred_at=datetime.now(tz=UTC),
        org_id=uuid7(),
        workspace_id=uuid7(),
        key_id=str(uuid7()),
        user_id=uuid7(),
        requested_model_id="gpt-test",
        requested_capabilities=frozenset(),
        model_id="gpt-test",
        provider_id="openai",
        bundle_id=uuid4(),
        input_tokens=10,
        output_tokens=5,
        token_usage_source=TokenUsageSource.PROVIDER,
        max_output_tokens=128,
        cost_usd="0.000004",
        cost_input_usd="0.000004",
        latency_ms=100,
        status="ok",
        stream=False,
        credential_id=uuid7(),
        credential_scope="workspace",
    )


def record(outbox: EventOutbox, event: RoutedUsageEventV1) -> None:
    with outbox.reserve() as reservation:
        reservation.record(event)


async def test_reserved_events_roundtrip_in_order(tmp_path, http_client):
    outbox = make_outbox(tmp_path, http_client)
    events = [
        make_event(uuid7()).model_copy(update={"token_usage_source": source}) for source in (TokenUsageSource.PROVIDER, TokenUsageSource.ESTIMATED)
    ]
    for event in events:
        record(outbox, event)
    assert await outbox.next_batch(10) == events
    await outbox.close()


async def test_reserved_events_are_idempotent_on_event_id(tmp_path, http_client):
    outbox = make_outbox(tmp_path, http_client)
    event = make_event(uuid7())
    record(outbox, event)
    record(outbox, event)
    assert await outbox.next_batch(10) == [event]
    await outbox.close()


async def test_reservations_are_bounded_by_capacity(tmp_path, http_client):
    outbox = make_outbox(tmp_path, http_client)
    with contextlib.ExitStack() as reservations:
        for _ in range(CAPACITY):
            reservations.enter_context(outbox.reserve())
        with pytest.raises(OutboxFullError):
            outbox.reserve()

    with outbox.reserve():
        pass
    await outbox.close()


async def test_transferred_slot_outlives_its_parent_reservation(tmp_path, http_client):
    outbox = make_outbox(tmp_path, http_client)
    with outbox.reserve() as reservation:
        transferred = reservation.transfer()

    assert (await outbox.stats())["reserved"] == 1

    with transferred:
        transferred.record(make_event(uuid7()))
    await outbox.close()


async def test_record_does_not_wait_for_a_sqlite_write_lock(tmp_path, http_client):
    outbox = make_outbox(tmp_path, http_client)
    lock = sqlite3.connect(tmp_path / "events.db")
    lock.execute("BEGIN IMMEDIATE")
    with outbox.reserve() as reservation:
        started = time.monotonic()
        reservation.record(make_event(uuid7()))
        elapsed = time.monotonic() - started

    assert elapsed < 0.1
    lock.rollback()
    lock.close()
    assert len(await outbox.next_batch(10)) == 1
    await outbox.close()


@respx.mock
async def test_flush_sends_batch_and_deletes(tmp_path, http_client):
    route = respx.post("http://cp.test/api/v1/events").mock(return_value=httpx.Response(200, json={"received": 2, "ingested": 2}))
    outbox = make_outbox(tmp_path, http_client)
    first, second = uuid7(), uuid7()
    record(outbox, make_event(first))
    record(outbox, make_event(second).model_copy(update={"token_usage_source": TokenUsageSource.ESTIMATED}))
    assert await outbox.export_once() == 2
    assert await outbox.next_batch(10) == []
    sent = json.loads(route.calls.last.request.content)
    assert [e["request_id"] for e in sent] == [str(first), str(second)]
    assert [e["token_usage_source"] for e in sent] == ["provider", "estimated"]
    assert route.calls.last.request.headers["authorization"] == "Bearer dp-token"


@respx.mock
async def test_failed_flush_keeps_the_events(tmp_path, http_client):
    respx.post("http://cp.test/api/v1/events").mock(return_value=httpx.Response(503))
    outbox = make_outbox(tmp_path, http_client)
    event = make_event(uuid7())
    record(outbox, event)
    with pytest.raises(httpx2.HTTPStatusError):
        await outbox.export_once()
    assert await outbox.next_batch(10) == [event]


async def test_only_one_holder_wins_the_flush_lease(tmp_path, http_client):
    a = make_outbox(tmp_path, http_client)
    b = make_outbox(tmp_path, http_client)
    a._owner = "worker-a"  # stand in for two processes on one shared cache dir
    b._owner = "worker-b"
    assert await a.claim_export(ttl=30, now=1000.0) is True
    assert await b.claim_export(ttl=30, now=1000.0) is False  # a still holds a live lease
    assert await b.claim_export(ttl=30, now=1040.0) is True  # a's lease expired, b takes over
    assert await a.claim_export(ttl=30, now=1041.0) is False
    await a.close()
    await b.close()


async def test_metrics_refresh_reads_the_shared_durable_backlog(tmp_path, http_client):
    first_metrics = DataPlaneMetrics()
    second_metrics = DataPlaneMetrics()
    config = make_config(tmp_path)
    assert isinstance(config.events, SqliteOutboxConfig)
    first = SqliteOutbox(config.events, http_client, first_metrics)
    second = SqliteOutbox(config.events, http_client, second_metrics)
    record(first, make_event(uuid7()))
    await first.next_batch(1)

    await second.refresh_metrics()

    assert "airmux_data_plane_metering_outbox_pending 1.0" in second_metrics.render().decode()
    await first.close()
    await second.close()


async def test_build_outbox_selects_kind(tmp_path, http_client):
    config = make_config(tmp_path)
    sqlite = build_outbox(config.events, http_client, DataPlaneMetrics())
    assert isinstance(sqlite, SqliteOutbox)
    devnull = make_config(tmp_path, outbox_kind="devnull")
    sink = build_outbox(devnull.events, http_client, DataPlaneMetrics())
    assert isinstance(sink, DevNullOutbox)
    await sqlite.close()
    await sink.close()


async def test_devnull_has_no_queue_capacity_or_stats():
    outbox = DevNullOutbox(DataPlaneMetrics())
    with outbox.reserve():
        assert await outbox.stats() == {}

    await outbox.close()


@respx.mock
async def test_a_flush_cycle_drains_more_than_one_batch(tmp_path, http_client):
    route = respx.post("http://cp.test/api/v1/events").mock(return_value=httpx.Response(200, json={"received": BATCH_SIZE, "ingested": BATCH_SIZE}))
    outbox = make_outbox(tmp_path, http_client)
    for _ in range(BATCH_SIZE + 1):
        record(outbox, make_event(uuid7()))

    assert await outbox.export_available() == BATCH_SIZE + 1
    assert await outbox.next_batch(1) == []
    assert route.call_count == 2


async def test_outbox_stats_distinguish_memory_and_durable_backlog(tmp_path, http_client):
    outbox = make_outbox(tmp_path, http_client)
    event = make_event(uuid7())
    with outbox.reserve():
        record(outbox, event)
        stats = await outbox.stats()

        assert stats["reserved"] == 1
        filled, durable = stats["filled"], stats["durable"]
        assert isinstance(filled, int)
        assert isinstance(durable, int)
        assert filled + durable == 1
        assert stats["pending"] == 2
        assert stats["capacity"] == CAPACITY
        oldest_age_s = stats["oldest_age_s"]
        assert oldest_age_s is not None
        assert oldest_age_s >= 0
    await outbox.close()


async def test_close_drains_filled_events_before_closing_storage(tmp_path, http_client):
    outbox = make_outbox(tmp_path, http_client)
    event = make_event(uuid7())
    record(outbox, event)

    await outbox.close()

    reopened = make_outbox(tmp_path, http_client)
    assert await reopened.next_batch(10) == [event]
    await reopened.close()


def test_default_outbox_capacity_is_ten_thousand():
    assert CAPACITY == 10_000


def test_metrics_do_not_expose_shutdown_only_state():
    metrics = DataPlaneMetrics().render().decode()
    assert "airmux_data_plane_metering_shutdown_drains" not in metrics
