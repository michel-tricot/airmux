from __future__ import annotations

import contextlib
import contextvars
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator
    from uuid import UUID

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
        return json.dumps(payload, separators=(",", ":"), default=str)


def configure_logger(logger: logging.Logger, *, dev: bool) -> None:
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s") if dev else JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def log_event(logger: logging.Logger, level: int, event: str, **fields: object) -> None:
    logger.log(level, event, extra={"event": event, "fields": fields})
