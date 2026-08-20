from __future__ import annotations

from pathlib import Path

from provider_parity.cases import load_cases

CASES = Path(__file__).parents[1] / "cases"


def test_checked_in_cases_are_valid_and_uniquely_named():
    cases = load_cases(CASES)

    assert len(cases) >= 15
    assert len({case.id for case in cases}) == len(cases)
    assert all(case.oracle.has_assertion for case in cases)
    assert {transport for case in cases for transport in case.transports} == {"buffered", "streamed"}


def test_parallel_tools_describes_the_interaction_in_one_place():
    case = next(case for case in load_cases(CASES) if case.id == "tools.parallel")

    assert case.requires.capabilities == frozenset({"tools", "parallel_tools"})
    assert case.oracle.tool_names == ("report_alpha", "report_beta")
    assert case.request.parallel_tool_calls


def test_content_cases_leave_room_for_reasoning_tokens():
    cases = {case.id: case for case in load_cases(CASES)}

    assert cases["text.basic"].request.max_tokens >= 512
    assert cases["text.multi-turn"].request.max_tokens >= 512
    assert cases["structured-output.json-object"].request.max_tokens >= 512
    assert cases["tools.single"].request.max_tokens >= 512
    assert cases["parameters.max-tokens"].request.max_tokens == 8
