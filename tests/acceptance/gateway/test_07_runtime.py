from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import httpx
import pytest
from gateway_harness import DIALECTS, FAMILIES, PROTOCOLS, SECOND_KEY, eventually, request_body, text_of
from upstream import TEXT, Reply

if TYPE_CHECKING:
    from gateway_harness import Dialect, Gateway
    from upstream import Family, ReportedUsage


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
def test_client_disconnect_records_partial_usage_and_other_requests_still_complete(gateway: Gateway, dialect: Dialect, family: Family):
    provider = gateway.add_provider(family)
    release = threading.Event()
    provider.replies["upstream-model-a"] = Reply(hold=release)
    gateway.start()
    with httpx.stream(
        "POST", gateway.url + PROTOCOLS["ingress"][dialect], headers=gateway.headers(dialect), json=request_body(dialect, stream=True)
    ) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("data: ") and ("hello" in line):
                break
        else:
            pytest.fail("stream ended before delivering content")
    (cancelled,) = gateway.events(1)
    assert cancelled.status == "cancelled"
    assert cancelled.stream is True
    assert cancelled.input_tokens is not None
    assert cancelled.output_tokens is not None
    assert cancelled.input_tokens > 0
    assert cancelled.output_tokens > 0
    assert cancelled.token_usage_source == "partial"
    release.set()
    assert gateway.request(dialect, model="model-b").status_code == 200
    assert [event.status for event in gateway.events(2)] == ["cancelled", "ok"]


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("usage", [None, "default"], ids=["estimated", "reported"])
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
def test_usage_is_estimated_when_absent_and_appended_across_restart(gateway: Gateway, family: Family, usage: ReportedUsage, stream: bool):
    provider = gateway.add_provider(family)
    provider.replies["upstream-model-a"] = Reply(usage=usage)
    gateway.start()
    assert gateway.request(stream=stream).status_code == 200
    (first,) = gateway.events(1)
    assert first.input_tokens is not None
    assert first.output_tokens is not None
    assert first.input_tokens > 0
    assert first.output_tokens > 0
    assert first.token_usage_source == ("estimated" if usage is None else "provider")
    gateway.stop()
    gateway.launch()
    eventually(gateway.ready)
    assert gateway.request(stream=stream).status_code == 200
    original, second = gateway.events(2)
    assert original == first
    assert original.event_id != second.event_id
    assert original.request_id != second.request_id
    assert original.bundle_id == second.bundle_id
    assert second.token_usage_source == first.token_usage_source


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("workers", [1, 2], ids=["one_worker", "two_workers"])
def test_concurrent_requests_keep_keys_content_and_events_separate(gateway: Gateway, dialect: Dialect, workers: int):
    provider = gateway.add_provider()
    provider.replies["upstream-model-a"] = Reply(text="answer A")
    provider.replies["upstream-model-b"] = Reply(text="answer B")
    gateway.start(workers)

    def complete(index: int):
        model = "model-a" if index % 2 == 0 else "model-b"
        key = SECOND_KEY if index % 2 else gateway.bundle["keys"][0]["token"]
        response = gateway.request(dialect, model=model, key=key)
        assert response.status_code == 200
        assert text_of(dialect, response) == ("answer A" if index % 2 == 0 else "answer B")

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(complete, range(24)))
    events = gateway.events(24)
    assert len({event.request_id for event in events}) == 24
    assert sum(event.key_id == "local-0" and event.model_id == "model-a" for event in events) == 12
    assert sum(event.key_id == "local-1" and event.model_id == "model-b" for event in events) == 12
    assert all(event.status == "ok" for event in events)
    assert len(provider.requests) == 24


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
def test_active_stream_keeps_its_snapshot_while_new_requests_use_rotated_keys_and_policies(gateway: Gateway, dialect: Dialect, family: Family):
    provider = gateway.add_provider(family)
    release = threading.Event()
    provider.replies["upstream-model-a"] = Reply(hold=release)
    gateway.start()
    rotated_key = "sk-inf-integration-rotated"
    with httpx.stream(
        "POST", gateway.url + PROTOCOLS["ingress"][dialect], headers=gateway.headers(dialect), json=request_body(dialect, stream=True)
    ) as response:
        assert response.status_code == 200
        lines = response.iter_lines()
        for line in lines:
            if line.startswith("data: ") and "hello" in line:
                break
        else:
            pytest.fail("stream ended before delivering content")
        gateway.bundle["keys"] = [{"token": rotated_key, "user_id": gateway.bundle["keys"][0]["user_id"]}]
        gateway.add_policy([{"kind": "models", "names": ["model-b"]}])
        gateway.write_files()
        observed = []

        def reloaded() -> bool:
            observed.append(gateway.request(dialect, key=rotated_key, model="model-b"))
            return observed[-1].status_code == 200

        eventually(reloaded)
        assert gateway.request(dialect).status_code == 401
        assert gateway.request(dialect, key=rotated_key).status_code == 403
        release.set()
        remaining = "\n".join(lines)
        assert "invalid_upstream_response" not in remaining
    events = gateway.events(3)
    successful = [event for event in events if event.status == "ok"]
    assert {event.model_id for event in successful} == {"model-a", "model-b"}
    assert len({event.bundle_id for event in successful}) == 2
    assert any(event.status == "denied" and event.model_id == "model-a" for event in events)


@pytest.mark.parametrize("invalid", ["malformed", "missing"], ids=["malformed_taxonomy", "missing_taxonomy"])
def test_bad_reload_preserves_snapshot_and_valid_replacement_recovers(gateway: Gateway, invalid: str):
    gateway.add_provider()
    gateway.start()
    assert gateway.request().status_code == 200
    (first,) = gateway.events(1)
    if invalid == "malformed":
        gateway.taxonomy_path.write_text("models: [{model_id: broken}]\n")
    else:
        gateway.taxonomy_path.unlink()
    preserved = []
    deadline = time.monotonic() + 10 * gateway.reload_interval_s

    while True:
        response = gateway.request()
        preserved.append(response)
        assert response.status_code == 200, response.text
        assert text_of("openai_chat_completions", response) == TEXT
        assert gateway.events(1 + len(preserved))[-1].bundle_id == first.bundle_id
        readiness = httpx.get(f"{gateway.url}/readyz", timeout=1)
        assert readiness.status_code == 200
        assert readiness.json() == {"status": "ready"}
        if time.monotonic() >= deadline:
            break
    gateway.taxonomy["models"][0]["model_id"] = "model-new"
    gateway.taxonomy["models"][0]["upstream_model"] = "upstream-model-new"
    gateway.write_files()
    observed = []

    def recovered() -> bool:
        observed.append(gateway.request(model="model-new"))
        return observed[-1].status_code == 200

    eventually(recovered)
    assert gateway.request().status_code == 404
    events = gateway.events(2 + len(preserved) + len(observed))
    assert events[-2].status == "ok"
    assert events[-2].model_id == "model-new"
    assert events[-2].bundle_id != first.bundle_id
    assert events[-1].status == "denied"


def test_invalid_configuration_is_rejected_before_gateway_start(gateway: Gateway):
    gateway.add_provider()
    gateway.write_files()
    gateway.bundle_path.write_text("keys: [invalid-token]\ntaxonomy: taxonomy.yml\n")
    gateway.launch()
    assert gateway.process is not None
    assert gateway.process.wait(timeout=10) != 0
    assert "keys" in (gateway.directory / "gateway.log").read_text()
    assert not gateway.events_path.exists()
