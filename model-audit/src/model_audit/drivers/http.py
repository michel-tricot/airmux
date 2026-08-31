from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import cast

import httpx

from model_audit.drivers.base import ClientDriver, Connection, access_error, status_failure, status_outcome
from model_audit.models import Case, Failure, Observation, Outcome, Transport
from model_audit.scenario import compile_scenario
from model_audit.surfaces import by_endpoint, discover
from model_audit.surfaces.base import SurfaceCodec, parse_sse


def _headers(connection: Connection, codec: SurfaceCodec) -> dict[str, str]:
    authentication = (
        {"Authorization": f"Bearer {connection.api_key}"}
        if connection.auth == "bearer"
        else {connection.auth.removeprefix("header_key:"): connection.api_key}
    )
    return {**connection.headers, **authentication, **codec.headers(), "accept": "application/json, text/event-stream"}


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
    access_code = access_error(connection, response.status_code, code)
    outcome = status_outcome(connection, response.status_code, code)
    return Observation(
        outcome=outcome,
        error_code=access_code or code,
        error_message=message,
        http_status=response.status_code,
        duration_ms=duration_ms,
        client_type=f"HTTP {response.status_code}",
        failure=status_failure(connection, response.status_code, code, message),
    )


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
        client_type=type(error).__name__,
        failure=Failure(
            kind="transient" if outcome == "transient" else "protocol",
            origin="client",
            retryable=outcome == "transient",
            code=code,
            message=str(error)[:500],
        ),
    )


def _body(connection: Connection, codec: SurfaceCodec, model: str, case: Case, transport: Transport) -> dict[str, object]:
    body = codec.encode(model, case, transport)
    return {connection.param_aliases.get(name, name): value for name, value in body.items()}


def _send(
    connection: Connection,
    codec: SurfaceCodec,
    request: dict[str, object],
    transport: Transport,
    started: float,
) -> tuple[Observation, Mapping[str, object] | None]:
    url = f"{connection.base_url.rstrip('/')}/{codec.endpoint}"
    try:
        with httpx.Client(timeout=connection.timeout_seconds) as client:
            if transport == "streamed":
                with client.stream("POST", url, headers=_headers(connection, codec), json=request) as response:
                    content = response.read().decode()
            else:
                response = client.post(url, headers=_headers(connection, codec), json=request)
                content = ""
    except httpx.TimeoutException as error:
        return _failure(error, started, "request_timeout", "transient"), None
    except httpx.HTTPError as error:
        return _failure(error, started, "connection_error", "transient"), None
    try:
        elapsed = (time.perf_counter() - started) * 1000
        if response.is_error:
            return _error_observation(connection, response, elapsed), None
        if transport == "streamed":
            observation = codec.decode_stream(parse_sse(content), elapsed)
            if observation.failure is not None:
                observation = observation.model_copy(update={"failure": observation.failure.model_copy(update={"origin": connection.route})})
            return observation, None
        payload = _json_payload(response)
        return codec.decode_buffered(payload, elapsed), payload
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as error:
        return _failure(error, started, "http_protocol_error", "error"), None


def _execute_scenario(connection: Connection, codec: SurfaceCodec, model: str, case: Case, transport: Transport) -> Observation:
    started = time.perf_counter()
    scenario = compile_scenario(case)
    if scenario.request_count > 1 and transport == "streamed":
        message = "provider-state continuation requires buffered transport"
        return _failure(ValueError(message), started, "harness_request_error", "error")
    first_body = _body(connection, codec, model, scenario.steps[0].case, transport)
    request = first_body
    payload = None
    observation = Observation(outcome="inconclusive", error_code="not_run")
    for index, step in enumerate(scenario.steps):
        if index > 0:
            if payload is None:
                return observation
            next_body = _body(connection, codec, model, step.case, transport)
            try:
                request = codec.continuation(first_body, payload, next_body)
            except ValueError as error:
                return _failure(error, started, "harness_request_error", "error")
        observation, payload = _send(connection, codec, request, transport, started)
        if observation.outcome != "success":
            return observation
    return observation


class HTTPDriver(ClientDriver):
    id = "http"
    mode = "api"

    def __init__(self) -> None:
        self.endpoints = frozenset(codec.endpoint for codec in discover().values())

    def execute(self, connection: Connection, endpoint: str, model: str, case: Case, transport: Transport) -> Observation:
        started = time.perf_counter()
        try:
            codec = by_endpoint(endpoint)
            return _execute_scenario(connection, codec, model, case, transport)
        except (TypeError, ValueError) as error:
            return Observation(
                outcome="inconclusive",
                error_code="harness_request_error",
                error_message=str(error)[:500],
                duration_ms=(time.perf_counter() - started) * 1000,
                client_type="HTTP",
                failure=Failure(kind="protocol", origin="harness", code="harness_request_error", message=str(error)[:500]),
            )
