from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from live_harness import CASES, LiveGateway, RequestBudget

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from tests.acceptance.gateway.upstream import Family


def pytest_configure(config: pytest.Config) -> None:
    missing = [name for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY") if not os.environ.get(name, "").strip()]
    if missing:
        message = "Missing live-provider credentials: " + ", ".join(missing)
        raise pytest.UsageError(message)
    if config.getoption("numprocesses", default=None):
        message = "Run live-provider acceptance tests without parallel pytest workers"
        raise pytest.UsageError(message)


@pytest.fixture(scope="session")
def request_budget() -> RequestBudget:
    return RequestBudget()


@pytest.fixture
def live_gateway(tmp_path: Path, family: Family, request_budget: RequestBudget) -> Iterator[LiveGateway]:
    gateway = LiveGateway(tmp_path, CASES[family], request_budget)
    try:
        yield gateway
    finally:
        gateway.close()
