from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
import pytest
from gateway_harness import DIALECTS, FAMILIES, PROTOCOLS, eventually, request_body, stream_payloads, streamed_text
from upstream import TEXT, Reply

if TYPE_CHECKING:
    from gateway_harness import Dialect, Gateway
    from upstream import Family

    from contract import UsageEvent


@dataclass(frozen=True)
class PricingCase:
    prices: tuple[float, float, float, float]
    input_cost: float
    anthropic_input_cost: float
    output_cost: float


@dataclass(frozen=True)
class TokenCase:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    input_cost: float
    anthropic_input_cost: float
    output_cost: float


def set_prices(gateway: Gateway, models: tuple[str, ...], prices: tuple[float, float, float, float]) -> None:
    for model in gateway.taxonomy["models"]:
        if model["model_id"] in models:
            model.update(
                {
                    "input_price_per_mtok": prices[0],
                    "output_price_per_mtok": prices[1],
                    "cache_read_price_per_mtok": prices[2],
                    "cache_write_price_per_mtok": prices[3],
                }
            )


def assert_cost(event: UsageEvent, input_cost: float, output_cost: float) -> None:
    assert (event.cost_input_usd, event.cost_output_usd, event.cost_usd) == pytest.approx(
        (input_cost, output_cost, input_cost + output_cost), rel=1e-12, abs=1e-15
    )


def wire_usage(family: Family, case: TokenCase) -> dict[str, object]:
    if family == "anthropic":
        return {
            "input_tokens": case.input_tokens - case.cache_read_tokens - case.cache_write_tokens,
            "output_tokens": case.output_tokens,
            "cache_read_input_tokens": case.cache_read_tokens,
            "cache_creation_input_tokens": case.cache_write_tokens,
        }
    if family == "openai_responses":
        return {
            "input_tokens": case.input_tokens,
            "output_tokens": case.output_tokens,
            "input_tokens_details": {"cached_tokens": case.cache_read_tokens},
        }
    return {
        "prompt_tokens": case.input_tokens,
        "completion_tokens": case.output_tokens,
        "prompt_tokens_details": {"cached_tokens": case.cache_read_tokens},
    }


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
@pytest.mark.parametrize(
    "case",
    [
        PricingCase((0, 0, 0, 0), 0, 0, 0),
        PricingCase((2.75, 8.125, 0, 0), 0.00001925, 0.00001375, 0.000024375),
        PricingCase((1.23456789, 9.87654321, 0.12345678, 4.56789123), 0.00000913580235, 0.00001580244903, 0.00002962962963),
        PricingCase((0.0001, 0.0002, 0.00001, 0.0003), 0.00000000074, 0.00000000114, 0.0000000006),
    ],
    ids=["free_model", "free_cache", "fractional_prices", "sub_microdollar_prices"],
)
def test_catalog_prices_determine_each_event_cost(gateway: Gateway, dialect: Dialect, family: Family, stream: bool, case: PricingCase):
    gateway.add_provider(family)
    set_prices(gateway, ("model-a",), case.prices)
    gateway.start()
    response = gateway.request(dialect, stream=stream)
    assert response.status_code == 200, response.text
    (event,) = gateway.events(1)
    assert event.status == "ok"
    assert (event.input_tokens, event.output_tokens, event.cache_read_tokens, event.cache_write_tokens) == (
        11,
        3,
        4,
        2 if family == "anthropic" else 0,
    )
    assert_cost(event, case.anthropic_input_cost if family == "anthropic" else case.input_cost, case.output_cost)


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
@pytest.mark.parametrize(
    "case",
    [
        TokenCase(1000, 40, 0, 0, 0.002, 0.002, 0.0002),
        TokenCase(1000, 40, 1000, 0, 0.00025, 0.00025, 0.0002),
        TokenCase(1000, 40, 300, 200, 0.001475, 0.001575, 0.0002),
        TokenCase(1000, 40, 0, 1000, 0.002, 0.0025, 0.0002),
        TokenCase(1000, 0, 0, 0, 0.002, 0.002, 0),
        TokenCase(1000, 0, 1000, 0, 0.00025, 0.00025, 0),
        TokenCase(1000, 0, 0, 1000, 0.002, 0.0025, 0),
        TokenCase(0, 40, 0, 0, 0, 0, 0.0002),
        TokenCase(1000000, 2000000, 0, 0, 2, 2, 10),
    ],
    ids=[
        "ordinary",
        "cache_reads",
        "mixed_cache",
        "cache_writes_when_reported",
        "zero_output",
        "cache_reads_zero_output",
        "cache_writes_zero_output",
        "zero_input",
        "million_token_units",
    ],
)
def test_reported_tokens_determine_the_event_cost(gateway: Gateway, family: Family, stream: bool, case: TokenCase):
    provider = gateway.add_provider(family)
    provider.replies["upstream-model-a"] = Reply(usage=wire_usage(family, case))
    gateway.start()
    response = gateway.request(stream=stream)
    assert response.status_code == 200, response.text
    usage = next(payload["usage"] for payload in stream_payloads(response) if "usage" in payload) if stream else response.json()["usage"]
    assert usage == {
        "input_tokens": case.input_tokens,
        "output_tokens": case.output_tokens,
        "cache_read_tokens": case.cache_read_tokens,
        "cache_write_tokens": case.cache_write_tokens if family == "anthropic" else 0,
        "estimated": False,
    }
    (event,) = gateway.events(1)
    assert event.status == "ok"
    assert (event.input_tokens, event.output_tokens, event.cache_read_tokens, event.cache_write_tokens) == (
        case.input_tokens,
        case.output_tokens,
        case.cache_read_tokens,
        case.cache_write_tokens if family == "anthropic" else 0,
    )
    assert_cost(event, case.anthropic_input_cost if family == "anthropic" else case.input_cost, case.output_cost)


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
def test_missing_usage_is_priced_from_estimated_tokens(gateway: Gateway, family: Family, stream: bool):
    provider = gateway.add_provider(family)
    provider.replies["upstream-model-a"] = Reply(text="one two", usage=None)
    gateway.start()
    response = gateway.request(stream=stream)
    assert response.status_code == 200, response.text
    usage = next(payload["usage"] for payload in stream_payloads(response) if "usage" in payload) if stream else response.json()["usage"]
    assert usage["estimated"] is True
    (event,) = gateway.events(1)
    assert event.status == "ok"
    assert (event.input_tokens, event.output_tokens, event.cache_read_tokens, event.cache_write_tokens) == (3, 2, 0, 0)
    assert_cost(event, 0.000006, 0.00001)


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
def test_denied_requests_have_no_metered_cost(gateway: Gateway, dialect: Dialect, stream: bool):
    provider = gateway.add_provider()
    gateway.add_policy([{"kind": "deny", "message": "Metering denial"}])
    gateway.start()
    assert gateway.request(dialect, stream=stream).status_code == 403
    assert provider.requests == []
    (event,) = gateway.events(1)
    assert event.status == "denied"
    assert (event.input_tokens, event.output_tokens, event.cache_read_tokens, event.cache_write_tokens) == (0, 0, 0, 0)
    assert_cost(event, 0, 0)


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
def test_fallback_prices_each_attempt_using_its_own_model(gateway: Gateway, dialect: Dialect, family: Family, stream: bool):
    primary = gateway.add_provider(family)
    backup_family: Family = "anthropic" if family != "anthropic" else "openai_responses"
    backup = gateway.add_provider(backup_family, name="backup", models=("model-c",))
    primary.replies["upstream-model-a"] = Reply(status=429)
    set_prices(gateway, ("model-c",), (10, 20, 1, 12.5))
    gateway.add_policy([{"kind": "fallback", "models": ["model-c"], "on": ["rate_limited"], "max_attempts": 2, "timeout_ms": 10000}])
    gateway.start()
    response = gateway.request(dialect, stream=stream)
    assert response.status_code == 200, response.text
    assert [request.body["model"] for request in primary.requests] == ["upstream-model-a"]
    assert [request.body["model"] for request in backup.requests] == ["upstream-model-c"]
    first, second = gateway.events(2)
    assert (first.status, first.model_id, first.provider_id) == ("rate_limited", "model-a", "stub")
    assert (first.input_tokens, first.output_tokens, first.cache_read_tokens, first.cache_write_tokens) == (3, 0, 0, 0)
    assert (second.status, second.model_id, second.provider_id) == ("ok", "model-c", "backup")
    assert (second.input_tokens, second.output_tokens, second.cache_read_tokens, second.cache_write_tokens) == (
        11,
        3,
        4,
        2 if backup_family == "anthropic" else 0,
    )
    assert first.request_id == second.request_id
    assert first.bundle_id == second.bundle_id
    assert first.credential_id != second.credential_id
    assert_cost(first, 0.000006, 0)
    assert_cost(second, 0.000079 if backup_family == "anthropic" else 0.000074, 0.00006)
    assert first.cost_usd + second.cost_usd == pytest.approx(0.000145 if backup_family == "anthropic" else 0.00014, rel=1e-12, abs=1e-15)


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize(
    "case",
    [
        TokenCase(11, 3, 4, 2, 0.000015, 0.000016, 0.000015),
        TokenCase(1000, 40, 1000, 0, 0.00025, 0.00025, 0.0002),
        TokenCase(1000, 40, 0, 1000, 0.002, 0.0025, 0.0002),
    ],
    ids=["mixed_usage", "only_cache_reads", "only_cache_writes"],
)
def test_disconnect_prices_only_observed_or_estimated_usage(gateway: Gateway, family: Family, case: TokenCase):
    provider = gateway.add_provider(family)
    release = threading.Event()
    provider.replies["upstream-model-a"] = Reply(text="one two", usage=wire_usage(family, case), hold=release)
    gateway.start()
    with httpx.stream(
        "POST", gateway.url + PROTOCOLS["ingress"]["canonical"], headers=gateway.headers(), json=request_body("canonical", stream=True)
    ) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("data: ") and json.loads(line[6:]).get("delta", {}).get("text") == "one two":
                break
        else:
            pytest.fail("stream ended before delivering content")
    (event,) = gateway.events(1)
    assert event.status == "cancelled"
    assert (event.input_tokens, event.output_tokens, event.cache_read_tokens, event.cache_write_tokens) == (
        (case.input_tokens, 2, case.cache_read_tokens, case.cache_write_tokens) if family == "anthropic" else (3, 2, 0, 0)
    )
    assert_cost(event, case.anthropic_input_cost if family == "anthropic" else 0.000006, 0.00001)
    release.set()
    assert gateway.request(model="model-b").status_code == 200
    _, second = gateway.events(2)
    assert second.status == "ok"
    assert second.request_id != event.request_id
    assert_cost(second, 0.000016 if family == "anthropic" else 0.000015, 0.000015)


@pytest.mark.parametrize("family", FAMILIES)
def test_active_stream_keeps_original_prices_after_catalog_reload(gateway: Gateway, family: Family):
    provider = gateway.add_provider(family)
    release = threading.Event()
    provider.replies["upstream-model-a"] = Reply(hold=release)
    gateway.start()
    assert gateway.request(model="model-b").status_code == 200
    (baseline,) = gateway.events(1)
    with httpx.stream(
        "POST", gateway.url + PROTOCOLS["ingress"]["canonical"], headers=gateway.headers(), json=request_body("canonical", stream=True)
    ) as response:
        assert response.status_code == 200
        received = []
        lines = response.iter_lines()
        for line in lines:
            received.append(line)
            if line.startswith("data: ") and json.loads(line[6:]).get("delta", {}).get("text") == TEXT:
                break
        else:
            pytest.fail("stream ended before delivering content")
        set_prices(gateway, ("model-a", "model-b"), (10, 20, 1, 12.5))
        gateway.write_files()
        observed = []

        def reloaded() -> bool:
            observed.append(gateway.request(model="model-b"))
            assert observed[-1].status_code == 200, observed[-1].text
            return gateway.events(1 + len(observed))[-1].bundle_id != baseline.bundle_id

        eventually(reloaded)
        release.set()
        complete = httpx.Response(200, text="\n".join([*received, *lines]))
        assert streamed_text("canonical", complete) == TEXT
        assert complete.text.splitlines().count("data: [DONE]") == 1
    events = gateway.events(2 + len(observed))
    assert events[-1].model_id == "model-a"
    assert events[-1].status == "ok"
    assert events[-1].bundle_id == baseline.bundle_id
    assert events[-2].model_id == "model-b"
    assert events[-2].bundle_id != baseline.bundle_id
    for event in events:
        if event.bundle_id == baseline.bundle_id:
            assert_cost(event, 0.000016 if family == "anthropic" else 0.000015, 0.000015)
        else:
            assert_cost(event, 0.000079 if family == "anthropic" else 0.000074, 0.00006)
