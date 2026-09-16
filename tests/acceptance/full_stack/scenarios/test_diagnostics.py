from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest
from stack_harness import ADMIN_PASSWORD, STUB_API_KEY, Stack

if TYPE_CHECKING:
    from pathlib import Path


def test_failed_scenario_retains_logs_after_service_and_fixture_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    artifacts = tmp_path / "artifacts"
    monkeypatch.setenv("AIRMUX_STACK_ARTIFACTS", str(artifacts))
    directory = tmp_path / "failed-scenario"
    directory.mkdir()
    deployment = Stack(directory)
    try:
        deployment.write_config()
        deployment.start_cp()
        deployment.collect_credentials()
        deployment.start_dp()
        deployment.wait_dp_ready()
        response = deployment.request()
        assert response.status_code == 200, response.text
        with pytest.raises(AssertionError, match="deliberate diagnostics failure"):
            assert response.status_code == 503, "deliberate diagnostics failure"
    finally:
        deployment.teardown()
    secrets = (
        ADMIN_PASSWORD,
        STUB_API_KEY,
        deployment.caller_api_key,
        deployment.env["AIRMUX_MANAGEMENT_KEY"],
        deployment.env["AIRMUX_DATAPLANE_TOKEN"],
    )
    shutil.rmtree(directory)
    logs = artifacts / directory.name
    assert {path.name for path in logs.iterdir()} == {"cp.log", "dp.log", "upstream.log", "commands.log"}
    assert "Finished server process" in (logs / "cp.log").read_text()
    assert "Finished server process" in (logs / "dp.log").read_text()
    assert '"status": 200' in (logs / "upstream.log").read_text()
    assert all(secret not in log.read_text() for log in logs.iterdir() for secret in secrets)
