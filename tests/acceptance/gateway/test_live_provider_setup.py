from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from tests.acceptance.live_providers.live_harness import RequestBudget


@pytest.mark.parametrize("present", [None, "OPENAI_API_KEY", "ANTHROPIC_API_KEY"])
def test_live_provider_collection_fails_without_credentials(tmp_path: Path, present: str | None) -> None:
    suite = Path(__file__).parents[1] / "live_providers"
    environment = {name: value for name, value in os.environ.items() if name not in {"OPENAI_API_KEY", "ANTHROPIC_API_KEY"}}
    if present:
        environment[present] = "test-key"
    result = subprocess.run(  # noqa: S603 trusted local pytest command
        [sys.executable, "-m", "pytest", str(suite), "--collect-only", "-q", "--basetemp", str(tmp_path / "collection")],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 4, result.stdout + result.stderr
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        if name != present:
            assert name in result.stderr
    assert "Missing live-provider credentials" in result.stderr


@pytest.mark.parametrize("limit", [None, True, 0, 1281, "128"])
def test_live_request_budget_rejects_invalid_output_limits(limit: object) -> None:
    budget = RequestBudget()
    assert not budget.reserve({"max_tokens": limit}, "max_tokens")
    assert budget.requests == 0


def test_live_request_budget_stops_after_thirty_requests() -> None:
    budget = RequestBudget()
    assert all(budget.reserve({"max_tokens": 1280}, "max_tokens") for _ in range(30))
    assert not budget.reserve({"max_tokens": 1280}, "max_tokens")
    assert budget.requests == 30
