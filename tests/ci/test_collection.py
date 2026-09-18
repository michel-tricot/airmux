from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("audit_first", [True, False])
def test_model_audit_and_gateway_sharding_collect_in_either_order(audit_first):
    suites = ["model-audit/tests", "tests/ci/test_gateway_sharding.py"]
    result = subprocess.run(  # noqa: S603 trusted local pytest command
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *(suites if audit_first else suites[::-1])],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_collected_node_ids_land_in_exactly_one_shard" in result.stdout
    assert "model-audit/tests/test_cases.py::" in result.stdout
