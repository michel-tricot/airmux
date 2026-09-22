from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, TextIO
from uuid import UUID

from pydantic_core import PydanticSerializationError, to_json

if TYPE_CHECKING:
    from collections.abc import Iterator

_MAX_BATCH_RECORDS = 100
_MAX_BATCH_CHARACTERS = 65_536
_FLUSH_INTERVAL_SECONDS = 0.1
_JSON_SCALARS = (str, int, float, Decimal, UUID)

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("airmux_request_id", default=None)


@contextlib.contextmanager
def request_context(request_id: UUID) -> Iterator[None]:
    token = _request_id.set(str(request_id))
    try:
        yield
    finally:
        _request_id.reset(token)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": getattr(record, "event", "log"),
            "message": record.getMessage(),
        }
        if request_id := _request_id.get():
            payload["request_id"] = request_id
        payload.update(getattr(record, "fields", {}))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if all(value is None or isinstance(value, _JSON_SCALARS) for value in payload.values()):
            try:
                return to_json(payload, ensure_ascii=True, fallback=str).decode()
            except (PydanticSerializationError, UnicodeError):
                pass
        return json.dumps(payload, separators=(",", ":"), default=str)


class BatchedStreamHandler(logging.StreamHandler):
    def __init__(self, stream: TextIO | None = None) -> None:
        super().__init__(stream)
        self._lines: list[str] = []
        self._characters = 0
        self._timer: asyncio.TimerHandle | None = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record) + self.terminator
        except (TypeError, ValueError, OverflowError):
            self.handleError(record)
            return
        self._lines.append(line)
        self._characters += len(line)
        if len(self._lines) >= _MAX_BATCH_RECORDS or self._characters >= _MAX_BATCH_CHARACTERS or record.levelno >= logging.ERROR:
            self.flush()
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.flush()
            return
        if self._timer is None:
            self._timer = loop.call_later(_FLUSH_INTERVAL_SECONDS, self.flush)

    def flush(self) -> None:
        self.acquire()
        try:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            if not self._lines:
                return
            text = "".join(self._lines)
            self._lines.clear()
            self._characters = 0
            try:
                self.stream.write(text)
                self.stream.flush()
            except (OSError, ValueError):
                self.handleError(logging.LogRecord(__name__, logging.ERROR, __file__, 0, "failed to write log batch", (), None))
        finally:
            self.release()

    def close(self) -> None:
        try:
            self.flush()
        finally:
            super().close()


def configure_logger(logger: logging.Logger, *, dev: bool) -> None:
    if logger.handlers:
        return
    handler = logging.StreamHandler() if dev else BatchedStreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s") if dev else JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def flush_logger(logger: logging.Logger) -> None:
    for handler in logger.handlers:
        handler.flush()


def log_event(logger: logging.Logger, level: int, event: str, **fields: object) -> None:
    logger.log(level, event, extra={"event": event, "fields": fields})
