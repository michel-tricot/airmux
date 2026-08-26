from __future__ import annotations

import time
from typing import TYPE_CHECKING, cast

import openai
from openai import OpenAI

from provider_parity.drivers.base import ClientDriver, Connection, access_error
from provider_parity.drivers.normalize import openai_chat, openai_chat_stream, openai_responses
from provider_parity.drivers.wire import openai_chat_options, openai_messages, openai_responses_options
from provider_parity.models import Case, Observation, Transport

if TYPE_CHECKING:
    from collections.abc import Mapping

    from openai.types.chat import ChatCompletionMessageParam
    from openai.types.responses import ResponseInputParam


def _unsupported(error: openai.APIStatusError) -> bool:
    message = str(error).casefold()
    return error.status_code in {400, 404, 422} and any(term in message for term in ("unsupported", "not support", "does not accept"))


class OpenAIDriver(ClientDriver):
    id = "openai"
    endpoints = frozenset({"chat/completions", "responses"})

    def execute(self, connection: Connection, endpoint: str, model: str, case: Case, transport: Transport) -> Observation:
        client = OpenAI(
            base_url=connection.base_url,
            api_key=connection.api_key,
            default_headers=connection.headers,
            timeout=connection.timeout_seconds,
            max_retries=0,
        )
        started = time.perf_counter()
        try:
            if endpoint == "responses":
                return self._responses(client, model, case, transport, started)
            if endpoint == "chat/completions":
                return self._chat(client, model, case, transport, started)
            message = f"OpenAI SDK does not support endpoint {endpoint}"
            raise ValueError(message)
        except openai.APIStatusError as error:
            elapsed = (time.perf_counter() - started) * 1000
            access_code = access_error(connection, error.status_code)
            return Observation(
                outcome="inconclusive" if access_code else "unsupported" if _unsupported(error) else "error",
                error_code=access_code or str(getattr(error, "code", None) or error.status_code),
                error_message=str(error)[:500],
                http_status=error.status_code,
                duration_ms=elapsed,
                sdk_type=type(error).__name__,
            )
        except openai.APITimeoutError as error:
            elapsed = (time.perf_counter() - started) * 1000
            return Observation(
                outcome="inconclusive",
                error_code="request_timeout",
                error_message=str(error)[:500],
                duration_ms=elapsed,
                sdk_type=type(error).__name__,
            )
        except openai.APIConnectionError as error:
            elapsed = (time.perf_counter() - started) * 1000
            return Observation(
                outcome="inconclusive",
                error_code="connection_error",
                error_message=str(error)[:500],
                duration_ms=elapsed,
                sdk_type=type(error).__name__,
            )
        except IndexError as error:
            elapsed = (time.perf_counter() - started) * 1000
            return Observation(
                outcome="error",
                error_code="sdk_protocol_error",
                error_message=str(error)[:500] or "OpenAI SDK could not fold the response stream",
                duration_ms=elapsed,
                sdk_type=type(error).__name__,
            )

    @staticmethod
    def _responses(client: OpenAI, model: str, case: Case, transport: Transport, started: float) -> Observation:
        response_input = cast("ResponseInputParam", openai_messages(case, True))
        body = openai_responses_options(case)
        if transport == "streamed":
            with client.responses.stream(model=model, input=response_input, extra_body=body) as stream:
                response = stream.get_final_response()
        else:
            response = client.responses.create(model=model, input=response_input, extra_body=body)
        elapsed = (time.perf_counter() - started) * 1000
        return openai_responses(cast("Mapping[str, object]", response.model_dump()), elapsed, type(response).__name__)

    @classmethod
    def _chat(cls, client: OpenAI, model: str, case: Case, transport: Transport, started: float) -> Observation:
        messages = cast("list[ChatCompletionMessageParam]", openai_messages(case, False))
        body = openai_chat_options(case)
        if transport == "buffered":
            completion = client.chat.completions.create(model=model, messages=messages, extra_body=body)
            elapsed = (time.perf_counter() - started) * 1000
            return openai_chat(cast("Mapping[str, object]", completion.model_dump()), elapsed, type(completion).__name__)
        stream = client.chat.completions.create(model=model, messages=messages, stream=True, stream_options={"include_usage": True}, extra_body=body)
        events = [cast("Mapping[str, object]", event.model_dump()) for event in stream]
        elapsed = (time.perf_counter() - started) * 1000
        return openai_chat_stream(events, elapsed, "Stream[ChatCompletionChunk]")
