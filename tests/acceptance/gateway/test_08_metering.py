from __future__ import annotations

import threading
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import httpx
import pytest
from gateway_harness import DIALECTS, FAMILIES, PROTOCOLS, eventually, request_body, stream_payloads, streamed_text
from upstream import DEFAULT_USAGE, TEXT, Reply

if TYPE_CHECKING:
    from gateway_harness import Dialect, Gateway
    from upstream import Family

    from contract import UsageEvent


@dataclass(frozen=True)
class MeteringExpectation:
    tokens: tuple[int, int, int, int]
    input_cost: str
    output_cost: str


@dataclass(frozen=True)
class TokenCase:
    reported_usage: dict[str, object]
    expected: MeteringExpectation


@dataclass(frozen=True)
class PricingCase:
    prices: tuple[str, str, str, str]
    expected: dict[Family, MeteringExpectation]


DEFAULT_EXPECTATIONS: dict[Family, MeteringExpectation] = {
    "openai_compatible": MeteringExpectation((11, 3, 4, 0), "0.000015", "0.000015"),
    "openai_responses": MeteringExpectation((11, 3, 4, 0), "0.000015", "0.000015"),
    "anthropic": MeteringExpectation((11, 3, 4, 2), "0.000016", "0.000015"),
}
RELOADED_EXPECTATIONS: dict[Family, MeteringExpectation] = {
    "openai_compatible": MeteringExpectation((11, 3, 4, 0), "0.000074", "0.00006"),
    "openai_responses": MeteringExpectation((11, 3, 4, 0), "0.000074", "0.00006"),
    "anthropic": MeteringExpectation((11, 3, 4, 2), "0.000079", "0.00006"),
}
TOKEN_CASES: dict[Family, dict[str, TokenCase]] = {
    "openai_compatible": {
        "ordinary": TokenCase(
            {"prompt_tokens": 1000, "completion_tokens": 40, "prompt_tokens_details": {"cached_tokens": 0}},
            MeteringExpectation((1000, 40, 0, 0), "0.002", "0.0002"),
        ),
        "cache_reads": TokenCase(
            {"prompt_tokens": 1000, "completion_tokens": 40, "prompt_tokens_details": {"cached_tokens": 1000}},
            MeteringExpectation((1000, 40, 1000, 0), "0.00025", "0.0002"),
        ),
        "mixed_cache": TokenCase(
            {"prompt_tokens": 1000, "completion_tokens": 40, "prompt_tokens_details": {"cached_tokens": 300}},
            MeteringExpectation((1000, 40, 300, 0), "0.001475", "0.0002"),
        ),
        "zero_output": TokenCase(
            {"prompt_tokens": 1000, "completion_tokens": 0, "prompt_tokens_details": {"cached_tokens": 0}},
            MeteringExpectation((1000, 0, 0, 0), "0.002", "0"),
        ),
        "cache_reads_zero_output": TokenCase(
            {"prompt_tokens": 1000, "completion_tokens": 0, "prompt_tokens_details": {"cached_tokens": 1000}},
            MeteringExpectation((1000, 0, 1000, 0), "0.00025", "0"),
        ),
        "zero_input": TokenCase(
            {"prompt_tokens": 0, "completion_tokens": 40, "prompt_tokens_details": {"cached_tokens": 0}},
            MeteringExpectation((0, 40, 0, 0), "0", "0.0002"),
        ),
        "million_token_units": TokenCase(
            {"prompt_tokens": 1000000, "completion_tokens": 2000000, "prompt_tokens_details": {"cached_tokens": 0}},
            MeteringExpectation((1000000, 2000000, 0, 0), "2", "10"),
        ),
    },
    "openai_responses": {
        "ordinary": TokenCase(
            {"input_tokens": 1000, "output_tokens": 40, "input_tokens_details": {"cached_tokens": 0}},
            MeteringExpectation((1000, 40, 0, 0), "0.002", "0.0002"),
        ),
        "cache_reads": TokenCase(
            {"input_tokens": 1000, "output_tokens": 40, "input_tokens_details": {"cached_tokens": 1000}},
            MeteringExpectation((1000, 40, 1000, 0), "0.00025", "0.0002"),
        ),
        "mixed_cache": TokenCase(
            {"input_tokens": 1000, "output_tokens": 40, "input_tokens_details": {"cached_tokens": 300}},
            MeteringExpectation((1000, 40, 300, 0), "0.001475", "0.0002"),
        ),
        "zero_output": TokenCase(
            {"input_tokens": 1000, "output_tokens": 0, "input_tokens_details": {"cached_tokens": 0}},
            MeteringExpectation((1000, 0, 0, 0), "0.002", "0"),
        ),
        "cache_reads_zero_output": TokenCase(
            {"input_tokens": 1000, "output_tokens": 0, "input_tokens_details": {"cached_tokens": 1000}},
            MeteringExpectation((1000, 0, 1000, 0), "0.00025", "0"),
        ),
        "zero_input": TokenCase(
            {"input_tokens": 0, "output_tokens": 40, "input_tokens_details": {"cached_tokens": 0}},
            MeteringExpectation((0, 40, 0, 0), "0", "0.0002"),
        ),
        "million_token_units": TokenCase(
            {"input_tokens": 1000000, "output_tokens": 2000000, "input_tokens_details": {"cached_tokens": 0}},
            MeteringExpectation((1000000, 2000000, 0, 0), "2", "10"),
        ),
    },
    "anthropic": {
        "ordinary": TokenCase(
            {"input_tokens": 1000, "output_tokens": 40, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
            MeteringExpectation((1000, 40, 0, 0), "0.002", "0.0002"),
        ),
        "cache_reads": TokenCase(
            {"input_tokens": 0, "output_tokens": 40, "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 0},
            MeteringExpectation((1000, 40, 1000, 0), "0.00025", "0.0002"),
        ),
        "mixed_cache": TokenCase(
            {"input_tokens": 500, "output_tokens": 40, "cache_read_input_tokens": 300, "cache_creation_input_tokens": 200},
            MeteringExpectation((1000, 40, 300, 200), "0.001575", "0.0002"),
        ),
        "cache_writes_when_reported": TokenCase(
            {"input_tokens": 0, "output_tokens": 40, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 1000},
            MeteringExpectation((1000, 40, 0, 1000), "0.0025", "0.0002"),
        ),
        "zero_output": TokenCase(
            {"input_tokens": 1000, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
            MeteringExpectation((1000, 0, 0, 0), "0.002", "0"),
        ),
        "cache_reads_zero_output": TokenCase(
            {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 0},
            MeteringExpectation((1000, 0, 1000, 0), "0.00025", "0"),
        ),
        "cache_writes_zero_output": TokenCase(
            {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 1000},
            MeteringExpectation((1000, 0, 0, 1000), "0.0025", "0"),
        ),
        "zero_input": TokenCase(
            {"input_tokens": 0, "output_tokens": 40, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
            MeteringExpectation((0, 40, 0, 0), "0", "0.0002"),
        ),
        "million_token_units": TokenCase(
            {"input_tokens": 1000000, "output_tokens": 2000000, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
            MeteringExpectation((1000000, 2000000, 0, 0), "2", "10"),
        ),
    },
}
DISCONNECT_CASES: dict[Family, dict[str, TokenCase]] = {
    "openai_compatible": {
        "mixed_usage": TokenCase(DEFAULT_USAGE["openai_compatible"], MeteringExpectation((3, 2, 0, 0), "0.000006", "0.00001")),
    },
    "openai_responses": {
        "mixed_usage": TokenCase(DEFAULT_USAGE["openai_responses"], MeteringExpectation((3, 2, 0, 0), "0.000006", "0.00001")),
    },
    "anthropic": {
        "mixed_usage": TokenCase(DEFAULT_USAGE["anthropic"], MeteringExpectation((11, 2, 4, 2), "0.000016", "0.00001")),
        "only_cache_reads": TokenCase(
            TOKEN_CASES["anthropic"]["cache_reads"].reported_usage, MeteringExpectation((1000, 2, 1000, 0), "0.00025", "0.00001")
        ),
        "only_cache_writes": TokenCase(
            TOKEN_CASES["anthropic"]["cache_writes_when_reported"].reported_usage, MeteringExpectation((1000, 2, 0, 1000), "0.0025", "0.00001")
        ),
    },
}
FALLBACK_CASES: dict[Family, tuple[Family, str]] = {
    "openai_compatible": ("anthropic", "0.000145"),
    "openai_responses": ("anthropic", "0.000145"),
    "anthropic": ("openai_responses", "0.00014"),
}


def set_prices(gateway: Gateway, models: tuple[str, ...], prices: tuple[str, str, str, str]) -> None:
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


def assert_cost(event: UsageEvent, input_cost: str, output_cost: str) -> None:
    input_amount = Decimal(input_cost)
    output_amount = Decimal(output_cost)
    assert (event.cost_input_usd, event.cost_output_usd, event.cost_usd) == (input_amount, output_amount, input_amount + output_amount)


def assert_metering(event: UsageEvent, expected: MeteringExpectation) -> None:
    assert (event.input_tokens, event.output_tokens, event.cache_read_tokens, event.cache_write_tokens) == expected.tokens
    assert_cost(event, expected.input_cost, expected.output_cost)


def assert_caller_usage(usage: dict[str, object], tokens: tuple[int, int, int, int]) -> None:
    input_tokens, output_tokens, cache_read_tokens, _cache_write_tokens = tokens
    assert usage == {
        "prompt_tokens": input_tokens,
        "completion_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "prompt_tokens_details": {"cached_tokens": cache_read_tokens},
    }


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
@pytest.mark.parametrize(
    "case",
    [
        PricingCase(
            ("0", "0", "0", "0"),
            {
                "openai_compatible": MeteringExpectation((11, 3, 4, 0), "0", "0"),
                "openai_responses": MeteringExpectation((11, 3, 4, 0), "0", "0"),
                "anthropic": MeteringExpectation((11, 3, 4, 2), "0", "0"),
            },
        ),
        PricingCase(
            ("2.75", "8.125", "0", "0"),
            {
                "openai_compatible": MeteringExpectation((11, 3, 4, 0), "0.00001925", "0.000024375"),
                "openai_responses": MeteringExpectation((11, 3, 4, 0), "0.00001925", "0.000024375"),
                "anthropic": MeteringExpectation((11, 3, 4, 2), "0.00001375", "0.000024375"),
            },
        ),
        PricingCase(
            ("1.234567", "9.876543", "0.123456", "4.567891"),
            {
                "openai_compatible": MeteringExpectation((11, 3, 4, 0), "0.000009135793", "0.000029629629"),
                "openai_responses": MeteringExpectation((11, 3, 4, 0), "0.000009135793", "0.000029629629"),
                "anthropic": MeteringExpectation((11, 3, 4, 2), "0.000015802441", "0.000029629629"),
            },
        ),
        PricingCase(
            ("0.0001", "0.0002", "0.00001", "0.0003"),
            {
                "openai_compatible": MeteringExpectation((11, 3, 4, 0), "0.00000000074", "0.0000000006"),
                "openai_responses": MeteringExpectation((11, 3, 4, 0), "0.00000000074", "0.0000000006"),
                "anthropic": MeteringExpectation((11, 3, 4, 2), "0.00000000114", "0.0000000006"),
            },
        ),
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
    assert_metering(event, case.expected[family])


@pytest.mark.parametrize(("family", "case_id"), [(family, case_id) for family in FAMILIES for case_id in TOKEN_CASES[family]])
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
def test_reported_tokens_determine_the_event_cost(gateway: Gateway, family: Family, stream: bool, case_id: str):
    case = TOKEN_CASES[family][case_id]
    provider = gateway.add_provider(family)
    provider.replies["upstream-model-a"] = Reply(usage=case.reported_usage)
    gateway.start()
    response = gateway.request(stream=stream)
    assert response.status_code == 200, response.text
    usage = next(payload["usage"] for payload in stream_payloads(response) if "usage" in payload) if stream else response.json()["usage"]
    assert_caller_usage(usage, case.expected.tokens)
    (event,) = gateway.events(1)
    assert event.status == "ok"
    assert_metering(event, case.expected)


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
def test_missing_usage_is_priced_from_estimated_tokens(gateway: Gateway, family: Family, stream: bool):
    provider = gateway.add_provider(family)
    provider.replies["upstream-model-a"] = Reply(text="one two", usage=None)
    gateway.start()
    response = gateway.request(stream=stream)
    assert response.status_code == 200, response.text
    usage = next(payload["usage"] for payload in stream_payloads(response) if "usage" in payload) if stream else response.json()["usage"]
    assert_caller_usage(usage, (0, 0, 0, 0))
    (event,) = gateway.events(1)
    assert event.status == "ok"
    assert (event.input_tokens, event.output_tokens, event.cache_read_tokens, event.cache_write_tokens) == (3, 2, 0, 0)
    assert_cost(event, "0.000006", "0.00001")


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
    assert_cost(event, "0", "0")


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
def test_fallback_prices_each_attempt_using_its_own_model(gateway: Gateway, dialect: Dialect, family: Family, stream: bool):
    primary = gateway.add_provider(family)
    backup_family, total_cost = FALLBACK_CASES[family]
    backup = gateway.add_provider(backup_family, name="backup", models=("model-c",))
    primary.replies["upstream-model-a"] = Reply(status=429)
    set_prices(gateway, ("model-c",), ("10", "20", "1", "12.5"))
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
    assert first.request_id == second.request_id
    assert first.bundle_id == second.bundle_id
    assert first.credential_id != second.credential_id
    assert_cost(first, "0.000006", "0")
    assert_metering(second, RELOADED_EXPECTATIONS[backup_family])
    assert first.cost_usd + second.cost_usd == Decimal(total_cost)


@pytest.mark.parametrize(("family", "case_id"), [(family, case_id) for family in FAMILIES for case_id in DISCONNECT_CASES[family]])
def test_disconnect_prices_only_observed_or_estimated_usage(gateway: Gateway, family: Family, case_id: str):
    case = DISCONNECT_CASES[family][case_id]
    provider = gateway.add_provider(family)
    release = threading.Event()
    provider.replies["upstream-model-a"] = Reply(text="one two", usage=case.reported_usage, hold=release)
    gateway.start()
    with httpx.stream(
        "POST",
        gateway.url + PROTOCOLS["ingress"]["openai_chat_completions"],
        headers=gateway.headers(),
        json=request_body("openai_chat_completions", stream=True),
    ) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("data: ") and "one two" in line:
                break
        else:
            pytest.fail("stream ended before delivering content")
    (event,) = gateway.events(1)
    assert event.status == "cancelled"
    assert_metering(event, case.expected)
    release.set()
    assert gateway.request(model="model-b").status_code == 200
    _, second = gateway.events(2)
    assert second.status == "ok"
    assert second.request_id != event.request_id
    assert_metering(second, DEFAULT_EXPECTATIONS[family])


@pytest.mark.parametrize("family", FAMILIES)
def test_active_stream_keeps_original_prices_after_catalog_reload(gateway: Gateway, family: Family):
    provider = gateway.add_provider(family)
    release = threading.Event()
    provider.replies["upstream-model-a"] = Reply(hold=release)
    gateway.start()
    assert gateway.request(model="model-b").status_code == 200
    (baseline,) = gateway.events(1)
    with httpx.stream(
        "POST",
        gateway.url + PROTOCOLS["ingress"]["openai_chat_completions"],
        headers=gateway.headers(),
        json=request_body("openai_chat_completions", stream=True),
    ) as response:
        assert response.status_code == 200
        received = []
        lines = response.iter_lines()
        for line in lines:
            received.append(line)
            if line.startswith("data: ") and TEXT in line:
                break
        else:
            pytest.fail("stream ended before delivering content")
        set_prices(gateway, ("model-a", "model-b"), ("10", "20", "1", "12.5"))
        gateway.write_files()
        observed = []

        def reloaded() -> bool:
            observed.append(gateway.request(model="model-b"))
            assert observed[-1].status_code == 200, observed[-1].text
            return gateway.events(1 + len(observed))[-1].bundle_id != baseline.bundle_id

        eventually(reloaded)
        release.set()
        complete = httpx.Response(200, text="\n".join([*received, *lines]))
        assert streamed_text("openai_chat_completions", complete) == TEXT
        assert complete.text.splitlines().count("data: [DONE]") == 1
    events = gateway.events(2 + len(observed))
    assert events[-1].model_id == "model-a"
    assert events[-1].status == "ok"
    assert events[-1].bundle_id == baseline.bundle_id
    assert events[-2].model_id == "model-b"
    assert events[-2].bundle_id != baseline.bundle_id
    for event in events:
        if event.bundle_id == baseline.bundle_id:
            assert_metering(event, DEFAULT_EXPECTATIONS[family])
        else:
            assert_metering(event, RELOADED_EXPECTATIONS[family])


ZERO_USAGE_CASES: dict[Family, TokenCase] = {
    "openai_compatible": TokenCase({"prompt_tokens": 0, "completion_tokens": 0}, MeteringExpectation((3, 2, 0, 0), "0.000006", "0.00001")),
    "anthropic": TokenCase(
        {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        MeteringExpectation((3, 2, 0, 0), "0.000006", "0.00001"),
    ),
    "openai_responses": TokenCase({"input_tokens": 0, "output_tokens": 0}, MeteringExpectation((0, 0, 0, 0), "0", "0")),
}


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
def test_all_zero_usage_distinguishes_authoritative_counts_from_estimates(gateway: Gateway, family: Family, stream: bool) -> None:
    case = ZERO_USAGE_CASES[family]
    provider = gateway.add_provider(family)
    provider.replies["upstream-model-a"] = Reply(text="one two", usage=case.reported_usage)
    gateway.start()
    response = gateway.request(stream=stream)
    assert response.status_code == 200, response.text
    usage = next(payload["usage"] for payload in stream_payloads(response) if "usage" in payload) if stream else response.json()["usage"]
    assert_caller_usage(usage, (0, 0, 0, 0))
    (event,) = gateway.events(1)
    assert event.status == "ok"
    assert_metering(event, case.expected)
