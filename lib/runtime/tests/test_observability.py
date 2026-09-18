from __future__ import annotations

import json
import logging

from airmux_runtime.observability import JsonFormatter, request_context
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
