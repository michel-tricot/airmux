from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from typing import cast

import httpx

from provider_parity.drivers.base import ClientDriver, Connection, access_error
from provider_parity.drivers.normalize import (
    anthropic_message,
    anthropic_stream,
    openai_chat,
    openai_chat_stream,
    openai_responses,
    openai_responses_stream,
)
from provider_parity.drivers.wire import body_of
from provider_parity.models import Case, Observation, Outcome, Transport

ERROR_STATUSES = {400, 404, 422}


def _headers(connection: Connection, endpoint: str) -> dict[str, str]:
    authentication = (
        {"Authorization": f"Bearer {connection.api_key}"}
        if connection.auth == "bearer"
        else {connection.auth.removeprefix("header_key:"): connection.api_key}
    )
    return {
        **connection.headers,
        **authentication,
        **({"anthropic-version": "2023-06-01"} if endpoint == "messages" else {}),
        "accept": "application/json, text/event-stream",
    }


def _events(body: str) -> tuple[Mapping[str, object], ...]:
    events: list[Mapping[str, object]] = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        data = "\n".join(line.removeprefix("data:").lstrip() for line in block.splitlines() if line.startswith("data:"))
        if not data or data == "[DONE]":
            continue
        value = json.loads(data)
        if isinstance(value, Mapping):
            events.append(cast("Mapping[str, object]", value))
    return tuple(events)


def _error_detail(payload: object, status_code: int) -> tuple[str, str]:
    document = cast("Mapping[str, object]", payload) if isinstance(payload, Mapping) else {}
    error = document.get("error")
    detail = cast("Mapping[str, object]", error) if isinstance(error, Mapping) else {}
    code = detail.get("code") or detail.get("type") or status_code
    message = detail.get("message") or document.get("message") or str(payload)
    return str(code), str(message)[:500]


def _error_observation(connection: Connection, response: httpx.Response, duration_ms: float) -> Observation:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        payload = response.text
    code, message = _error_detail(payload, response.status_code)
    access_code = access_error(connection, response.status_code)
    unsupported = response.status_code in ERROR_STATUSES and any(
        term in message.casefold() for term in ("unsupported", "not support", "does not accept")
    )
    return Observation(
        outcome="inconclusive" if access_code else "unsupported" if unsupported else "error",
        error_code=access_code or code,
        error_message=message,
        http_status=response.status_code,
        duration_ms=duration_ms,
        sdk_type=f"HTTP {response.status_code}",
    )


def _buffered(endpoint: str, payload: Mapping[str, object], duration_ms: float) -> Observation:
    if endpoint == "chat/completions":
        return openai_chat(payload, duration_ms, "HTTP JSON")
    if endpoint == "responses":
        return openai_responses(payload, duration_ms, "HTTP JSON")
    if endpoint == "messages":
        return anthropic_message(payload, duration_ms, "HTTP JSON")
    message = f"raw HTTP client does not support endpoint {endpoint}"
    raise ValueError(message)


def _streamed(endpoint: str, events: Sequence[Mapping[str, object]], duration_ms: float) -> Observation:
    if endpoint == "chat/completions":
        return openai_chat_stream(events, duration_ms, "HTTP SSE")
    if endpoint == "responses":
        return openai_responses_stream(events, duration_ms, "HTTP SSE")
    if endpoint == "messages":
        return anthropic_stream(events, duration_ms, "HTTP SSE")
    message = f"raw HTTP client does not support endpoint {endpoint}"
    raise ValueError(message)


def _json_payload(response: httpx.Response) -> Mapping[str, object]:
    payload = response.json()
    if not isinstance(payload, Mapping):
        message = "provider response is not a JSON object"
        raise TypeError(message)
    return cast("Mapping[str, object]", payload)


def _failure(error: Exception, started: float, code: str, outcome: Outcome) -> Observation:
    return Observation(
        outcome=outcome,
        error_code=code,
        error_message=str(error)[:500],
        duration_ms=(time.perf_counter() - started) * 1000,
        sdk_type=type(error).__name__,
    )


def _send(
    connection: Connection,
    endpoint: str,
    request: dict[str, object],
    transport: Transport,
    started: float,
) -> Observation:
    url = f"{connection.base_url.rstrip('/')}/{endpoint}"
    try:
        with httpx.Client(timeout=connection.timeout_seconds) as client:
            if transport == "streamed":
                with client.stream("POST", url, headers=_headers(connection, endpoint), json=request) as response:
                    content = response.read().decode()
            else:
                response = client.post(url, headers=_headers(connection, endpoint), json=request)
                content = ""
    except httpx.TimeoutException as error:
        return _failure(error, started, "request_timeout", "inconclusive")
    except httpx.HTTPError as error:
        return _failure(error, started, "connection_error", "inconclusive")
    try:
        elapsed = (time.perf_counter() - started) * 1000
        if response.is_error:
            observation = _error_observation(connection, response, elapsed)
        elif transport == "streamed":
            observation = _streamed(endpoint, _events(content), elapsed)
        else:
            observation = _buffered(endpoint, _json_payload(response), elapsed)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as error:
        return _failure(error, started, "http_protocol_error", "error")
    else:
        return observation


class HTTPDriver(ClientDriver):
    id = "http"
    endpoints = frozenset({"chat/completions", "responses", "messages"})

    def execute(self, connection: Connection, endpoint: str, model: str, case: Case, transport: Transport) -> Observation:
        started = time.perf_counter()
        try:
            request = body_of(endpoint, model, case, transport)
        except (TypeError, ValueError) as error:
            return Observation(
                outcome="inconclusive",
                error_code="harness_request_error",
                error_message=str(error)[:500],
                duration_ms=(time.perf_counter() - started) * 1000,
                sdk_type="HTTP",
            )
        return _send(connection, endpoint, cast("dict[str, object]", request), transport, started)
