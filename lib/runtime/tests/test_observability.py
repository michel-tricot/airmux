from __future__ import annotations

import asyncio
import io
import json
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

import pytest

from airmux_runtime.observability import JsonFormatter, configure_logger, flush_logger, log_event, request_context
from contract import uuid7


def test_json_logs_include_the_request_context():
    request_id = uuid7()
    record = logging.LogRecord("airmux", logging.INFO, "", 0, "usage_recorded", (), None)
    record.__dict__.update(event="usage_recorded", fields={"outcome": "success"})

    with request_context(request_id):
        payload = json.loads(JsonFormatter().format(record))

    assert payload["request_id"] == str(request_id)
    assert payload["event"] == "usage_recorded"
    assert payload["outcome"] == "success"


class LogOutput(io.StringIO):
    def __init__(self):
        super().__init__()
        self.batches = []

    def write(self, text):
        self.batches.append(text)
        return super().write(text)


@pytest.fixture
def log_output(monkeypatch):
    output = LogOutput()
    monkeypatch.setattr(sys, "stderr", output)
    logger = logging.getLogger(f"batch-test-{uuid7()}")
    logger.propagate = False
    configure_logger(logger, dev=False)
    yield logger, output
    for handler in logger.handlers:
        handler.close()


async def test_production_logs_batch_without_losing_request_context(log_output):
    logger, output = log_output
    request_ids = [uuid7() for _ in range(100)]
    for index, request_id in enumerate(request_ids):
        with request_context(request_id):
            log_event(logger, logging.INFO, "usage_recorded", index=index)
        if index < 99:
            assert output.getvalue() == ""
    assert len(output.batches) == 1
    payloads = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [p["request_id"] for p in payloads] == [str(request_id) for request_id in request_ids]
    assert [p["index"] for p in payloads] == list(range(100))


async def test_low_volume_logs_flush_while_idle(log_output):
    logger, output = log_output
    log_event(logger, logging.INFO, "usage_recorded")
    assert output.getvalue() == ""
    await asyncio.sleep(0.15)
    assert json.loads(output.getvalue())["event"] == "usage_recorded"


async def test_errors_flush_preceding_logs_and_tracebacks(log_output):
    logger, output = log_output
    log_event(logger, logging.INFO, "before_error")
    assert output.getvalue() == ""
    try:
        int("upstream failed")
    except ValueError:
        logger.exception("request_failed")
    payloads = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [p["message"] for p in payloads] == ["before_error", "request_failed"]
    assert "ValueError:" in payloads[1]["exception"]
    assert "upstream failed" in payloads[1]["exception"]
    assert len(output.batches) == 1


@pytest.mark.parametrize("close", [False, True])
async def test_close_flushes_once_and_cancels_pending_output(log_output, close):
    logger, output = log_output
    log_event(logger, logging.INFO, "before_close")
    assert output.getvalue() == ""
    if close:
        logger.handlers[0].close()
    else:
        flush_logger(logger)
    output.close()
    await asyncio.sleep(0.15)
    assert len(output.batches) == 1
    assert json.loads(output.batches[0])["event"] == "before_close"


async def test_large_logs_do_not_accumulate_until_the_record_limit(log_output):
    logger, output = log_output
    text = "x" * 40_000
    log_event(logger, logging.INFO, "large", text=text)
    assert output.getvalue() == ""
    log_event(logger, logging.INFO, "large", text=text)
    assert [json.loads(line)["text"] for line in output.getvalue().splitlines()] == [text, text]


def test_logging_without_an_event_loop_is_immediate(log_output):
    logger, output = log_output
    log_event(logger, logging.INFO, "startup")
    assert json.loads(output.getvalue())["event"] == "startup"


async def test_thread_logging_flushes_in_order(log_output):
    logger, output = log_output
    log_event(logger, logging.INFO, "in_loop")
    assert output.getvalue() == ""
    await asyncio.to_thread(log_event, logger, logging.INFO, "in_thread")
    assert [json.loads(line)["event"] for line in output.getvalue().splitlines()] == ["in_loop", "in_thread"]


async def test_development_logs_are_immediate(monkeypatch):
    output = LogOutput()
    monkeypatch.setattr(sys, "stderr", output)
    logger = logging.getLogger(f"dev-test-{uuid7()}")
    configure_logger(logger, dev=True)
    try:
        logger.info("usage_recorded")
        assert output.getvalue() == "INFO:     usage_recorded\n"
    finally:
        logger.handlers[0].close()


class FailingLogOutput(LogOutput):
    failing = True

    def write(self, text):
        if self.failing:
            message = "log destination unavailable"
            raise OSError(message)
        return super().write(text)


@pytest.mark.parametrize("flush_on_error", [False, True])
async def test_failed_writes_do_not_fail_requests_or_replay_old_batches(log_output, flush_on_error, capsys):
    logger, _output = log_output
    output = FailingLogOutput()
    logger.handlers[0].setStream(output)
    log_event(logger, logging.ERROR if flush_on_error else logging.INFO, "lost_batch")
    if not flush_on_error:
        await asyncio.sleep(0.15)
    assert "log destination unavailable" in capsys.readouterr().err
    assert output.getvalue() == ""
    output.failing = False
    log_event(logger, logging.ERROR, "recovered")
    assert json.loads(output.getvalue())["event"] == "recovered"


async def test_formatting_errors_do_not_discard_preceding_logs(log_output, capsys):
    logger, output = log_output
    log_event(logger, logging.INFO, "before_bad_format")
    logger.handlers[0].handle(logging.LogRecord("batch-test", logging.INFO, "", 0, "%d", ("not a number",), None))
    logger.handlers[0].flush()
    assert "TypeError" in capsys.readouterr().err
    payloads = [json.loads(line) for line in output.getvalue().splitlines() if line.startswith("{")]
    assert [p["event"] for p in payloads] == ["before_bad_format"]


class Outcome(StrEnum):
    OK = "ok"


@dataclass
class LogDetail:
    count: int


@pytest.mark.parametrize(
    "fields",
    [
        {"cost": Decimal("0.000202"), "id": UUID(int=1), "outcome": Outcome.OK, "optional": None, "stream": False},
        {"text": 'café \u2603 "quoted"\n', "count": 10**30, "latency": 1.25},
        {"text": "\ud800"},
        {"nested": {"optional": None, "cost": Decimal("1.20")}, "values": [1, None]},
        {"detail": LogDetail(3), "date": datetime(2026, 1, 2, tzinfo=UTC), "bytes": b"hello"},
        {"positive": float("inf"), "negative": float("-inf")},
    ],
)
def test_json_log_fields_preserve_their_encoding(fields):
    record = logging.LogRecord("airmux", logging.INFO, "", 0, "encoded", (), None)
    record.__dict__.update(fields=fields)
    actual = json.loads(JsonFormatter().format(record))
    expected = json.loads(json.dumps(fields, default=str))
    assert {key: actual[key] for key in fields} == expected
