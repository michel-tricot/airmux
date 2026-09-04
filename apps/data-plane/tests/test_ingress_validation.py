from __future__ import annotations

import pytest
import respx
from conftest import mock_control_plane
from starlette.testclient import TestClient

from data_plane.errors import UnsupportedFeatureError
from data_plane.ingress import REGISTRY
from data_plane.proxy import RequestRejectedError, _parse


def request_body(dialect):
    if dialect == "openai_responses":
        return {"model": "gpt-test", "input": [{"role": "user", "content": "hello"}]}
    return {"model": "gpt-test", "messages": [{"role": "user", "content": "hello"}]}


@pytest.mark.parametrize("dialect", REGISTRY)
@pytest.mark.parametrize(("field", "value"), [("stream", "false"), ("stream", 1), ("model", 123), ("parallel_tool_calls", "false"), ("tools", 42)])
def test_malformed_request_fields_are_rejected(dialect, field, value):
    body = {**request_body(dialect), field: value}
    with pytest.raises(RequestRejectedError) as rejection:
        _parse(body, REGISTRY[dialect])
    assert rejection.value.status == 400
    assert rejection.value.code == "invalid_request"


@pytest.mark.parametrize("dialect", REGISTRY)
def test_unknown_message_role_is_rejected(dialect):
    field = "input" if dialect == "openai_responses" else "messages"
    body = {**request_body(dialect), field: [{"role": "banana", "content": "hello"}]}
    with pytest.raises(RequestRejectedError) as rejection:
        _parse(body, REGISTRY[dialect])
    assert rejection.value.status == 400


@pytest.mark.parametrize("dialect", REGISTRY)
def test_unknown_content_is_never_silently_discarded(dialect):
    field = "input" if dialect == "openai_responses" else "messages"
    text_kind = "input_text" if dialect == "openai_responses" else "text"
    content = [{"type": text_kind, "text": "hello"}, {"type": "banana", "text": "lost"}]
    body = {**request_body(dialect), field: [{"role": "user", "content": content}]}
    with pytest.raises(RequestRejectedError) as rejection:
        _parse(body, REGISTRY[dialect])
    assert rejection.value.status == 400


@pytest.mark.parametrize("dialect", REGISTRY)
def test_malformed_reasoning_is_rejected(dialect):
    field = "thinking" if dialect == "anthropic" else "reasoning"
    with pytest.raises(RequestRejectedError) as rejection:
        _parse({**request_body(dialect), field: 42}, REGISTRY[dialect])
    assert rejection.value.code == "invalid_request"


@pytest.mark.parametrize("dialect", REGISTRY)
@pytest.mark.parametrize("stream", [False, True])
def test_boolean_stream_mode_is_preserved(dialect, stream):
    request, adjustments = _parse({**request_body(dialect), "stream": stream}, REGISTRY[dialect])
    assert request.stream is stream
    assert adjustments == []


@pytest.mark.parametrize("dialect", REGISTRY)
@pytest.mark.parametrize("content", [42, [{"type": "text", "text": 42}], [{"type": "text", "text": None}], [{"type": "text"}]])
def test_malformed_message_content_is_rejected(dialect, content):
    field = "input" if dialect == "openai_responses" else "messages"
    body = {**request_body(dialect), field: [{"role": "user", "content": content}]}
    with pytest.raises(RequestRejectedError) as rejection:
        _parse(body, REGISTRY[dialect])
    assert rejection.value.code == "invalid_request"


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (UnsupportedFeatureError("feature unavailable"), "unsupported_feature"),
        (ValueError("unsupported_feature: ordinary validation"), "invalid_request"),
    ],
)
def test_error_classification_does_not_depend_on_message_text(error, code, monkeypatch):
    def reject(body):
        raise error

    monkeypatch.setattr(REGISTRY["canonical"], "parse", reject)
    with pytest.raises(RequestRejectedError) as rejection:
        _parse(request_body("canonical"), REGISTRY["canonical"])
    assert rejection.value.code == code
    assert rejection.value.message == str(error)


@pytest.mark.parametrize("dialect", REGISTRY)
@respx.mock
def test_invalid_stream_mode_returns_a_json_error(dialect, api_key, dp_app):
    mock_control_plane()
    with TestClient(dp_app) as client:
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "x-airllm-dialect": dialect},
            json={**request_body(dialect), "stream": "false"},
        )
    assert response.status_code == 400
    assert response.headers["content-type"] == "application/json"
    assert "invalid_request" in response.json()["error"].values()
