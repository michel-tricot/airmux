from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import httpx
from tests.acceptance.full_stack.stack_harness import STUB_API_KEY, _StubServer
from tests.diagnostics import retain_logs

if TYPE_CHECKING:
    from pathlib import Path


def test_retained_logs_survive_cleanup_and_exclude_credentials(tmp_path: Path):
    deployment = tmp_path / "deployment"
    deployment.mkdir()
    for name in ("cp.log", "dp.log", "upstream.log"):
        (deployment / name).write_text("HTTP 503\nAssertionError: expected 200\nBearer test-token\ncookie=test-cookie\n")
    for name in (".env", "config.yml", "private.pem", "secrets/raw", "unexpected.log"):
        secret = deployment / name
        secret.parent.mkdir(exist_ok=True)
        secret.write_text("private credential")
    destination = tmp_path / "artifacts" / "failed-scenario"
    retain_logs(deployment, destination, ("cp.log", "dp.log", "upstream.log"), ("test-token", "test-cookie"))
    shutil.rmtree(deployment)
    assert {path.name for path in destination.iterdir()} == {"cp.log", "dp.log", "upstream.log"}
    for log in destination.iterdir():
        assert log.read_text() == "HTTP 503\nAssertionError: expected 200\nBearer [REDACTED]\ncookie=[REDACTED]\n"


def test_stub_log_records_status_without_request_credentials_or_body(tmp_path: Path):
    log = tmp_path / "upstream.log"
    upstream = _StubServer(("127.0.0.1", 0), log)
    upstream.start()
    try:
        response = httpx.post(
            f"http://127.0.0.1:{upstream.server_port}/chat?token=private-cookie",
            headers={"Authorization": f"Bearer {STUB_API_KEY}", "Cookie": "session=private-cookie"},
            json={"messages": [{"role": "user", "content": "private body"}]},
        )
        assert response.status_code == 200
    finally:
        upstream.shutdown()
        upstream.server_close()
    contents = log.read_text()
    assert '"status": 200' in contents
    assert '"request": 1' in contents
    assert all(secret not in contents for secret in (STUB_API_KEY, "private-cookie", "private body"))
