"""Acceptance #7: an expired bundle (expires_at in the past) is handled per the configured
policy and logged. Default serve_and_warn keeps serving; refuse stops serving. A zero staleness
bound makes the freshly compiled bundle expire the moment it is issued."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from conftest import Stack


def test_expired_bundle_served_with_warning_by_default(stack: Stack) -> None:
    stack.write_config(staleness_bound_hours=0, staleness_policy="serve_and_warn")
    stack.start_cp()
    stack.collect_tokens()
    stack.start_dp()
    stack.wait_dp_ready()

    assert stack.readyz() == 200
    assert stack.wait_dp_log("serving stale per policy")


def test_expired_bundle_refused_when_policy_is_refuse(stack: Stack) -> None:
    stack.write_config(staleness_bound_hours=0, staleness_policy="refuse")
    stack.start_cp()
    stack.collect_tokens()
    stack.start_dp()

    assert stack.wait_dp_log("policy is refuse")
    assert stack.readyz() == 503
