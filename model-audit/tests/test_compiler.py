from __future__ import annotations

from model_audit.compiler import compile_pair, compile_request
from model_audit.models import Request
from model_audit.surfaces import discover
from tests.helpers import case, target


def test_surface_codecs_are_discovered_without_a_registry():
    codecs = discover()

    assert set(codecs) == {"oai", "oai_responses", "anthropic"}
    assert tuple(codecs) == ("oai_responses", "oai", "anthropic")
    assert {codec.endpoint for codec in codecs.values()} == {"chat/completions", "responses", "messages"}


def test_cross_surface_requests_have_the_same_semantic_fingerprint():
    codecs = discover()

    compiled = compile_pair(target(), codecs["oai"], codecs["anthropic"], case(), "buffered")

    assert compiled.direct.semantic_fingerprint == compiled.gateway.semantic_fingerprint
    assert compiled.direct.redacted_body["max_tokens"] == 1024
    assert compiled.gateway.redacted_body["max_tokens"] == 1024


def test_request_artifacts_redact_inline_media():
    codecs = discover()
    audit_case = case(
        request=Request(
            messages=(
                {
                    "role": "user",
                    "content": [{"type": "image", "media_type": "image/png", "data": "c2VjcmV0"}],
                },
            )
        )
    )

    artifact = compile_request(codecs["anthropic"], "model", audit_case, "buffered")

    messages = artifact.redacted_body["messages"]
    assert isinstance(messages, list)
    message = messages[0]
    assert isinstance(message, dict)
    content = message["content"]
    assert isinstance(content, list)
    block = content[0]
    assert isinstance(block, dict)
    source = block["source"]
    assert isinstance(source, dict)
    data = source["data"]
    assert isinstance(data, str)
    assert data.startswith("<content:")
    assert "c2VjcmV0" not in artifact.model_dump_json()
