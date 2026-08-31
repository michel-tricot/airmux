from __future__ import annotations

import time
from typing import TYPE_CHECKING, cast

import anthropic
from anthropic import Anthropic

from model_audit.drivers.base import ClientDriver, Connection, access_error, status_outcome
from model_audit.drivers.normalize import anthropic_message
from model_audit.drivers.wire import anthropic_parts
from model_audit.models import Case, Observation, Transport

if TYPE_CHECKING:
    from collections.abc import Mapping

    from anthropic.types import MessageParam


def _sdk_base_url(base_url: str) -> str:
    return base_url.rstrip("/").removesuffix("/v1")


class AnthropicDriver(ClientDriver):
    id = "anthropic"
    mode = "sdk"
    endpoints = frozenset({"messages"})

    def execute(self, connection: Connection, endpoint: str, model: str, case: Case, transport: Transport) -> Observation:
        if endpoint not in self.endpoints:
            message = f"anthropic SDK does not support endpoint {endpoint}"
            raise ValueError(message)
        if connection.auth == "bearer":
            client = Anthropic(
                base_url=_sdk_base_url(connection.base_url),
                api_key="unused",
                auth_token=connection.api_key,
                default_headers=connection.headers,
                timeout=connection.timeout_seconds,
                max_retries=0,
            )
        else:
            client = Anthropic(
                base_url=_sdk_base_url(connection.base_url),
                api_key=connection.api_key,
                default_headers=connection.headers,
                timeout=connection.timeout_seconds,
                max_retries=0,
            )
        messages, extra = anthropic_parts(case)
        started = time.perf_counter()
        try:
            message_params = cast("list[MessageParam]", messages)
            if transport == "streamed":
                with client.messages.stream(model=model, max_tokens=case.request.max_tokens, messages=message_params, extra_body=extra) as stream:
                    message = stream.get_final_message()
            else:
                message = client.messages.create(model=model, max_tokens=case.request.max_tokens, messages=message_params, extra_body=extra)
            elapsed = (time.perf_counter() - started) * 1000
            return anthropic_message(cast("Mapping[str, object]", message.model_dump()), elapsed, type(message).__name__)
        except anthropic.APIStatusError as error:
            elapsed = (time.perf_counter() - started) * 1000
            error_code = str(getattr(error, "code", None) or error.status_code)
            access_code = access_error(connection, error.status_code, error_code)
            return Observation(
                outcome=status_outcome(connection, error.status_code, error_code),
                error_code=access_code or error_code,
                error_message=str(error)[:500],
                http_status=error.status_code,
                duration_ms=elapsed,
                client_type=type(error).__name__,
            )
        except anthropic.APITimeoutError as error:
            elapsed = (time.perf_counter() - started) * 1000
            return Observation(
                outcome="transient",
                error_code="request_timeout",
                error_message=str(error)[:500],
                duration_ms=elapsed,
                client_type=type(error).__name__,
            )
        except anthropic.APIConnectionError as error:
            elapsed = (time.perf_counter() - started) * 1000
            return Observation(
                outcome="transient",
                error_code="connection_error",
                error_message=str(error)[:500],
                duration_ms=elapsed,
                client_type=type(error).__name__,
            )
