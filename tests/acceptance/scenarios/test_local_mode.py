"""Acceptance: the data plane serves from a hand-written bundle, with no control plane anywhere.

No Postgres, no bootstrap, no signature. The operator writes two files and sets one
environment variable; the same request path serves. This is the local mode of the two-source
design: one BundleV1, one admit(), a different door."""

from __future__ import annotations

import json
import signal
import sqlite3
import subprocess
import threading
from http.server import ThreadingHTTPServer
from typing import TYPE_CHECKING

import httpx
from conftest import _bin, _free_port, _poll, _StubHandler

if TYPE_CHECKING:
    from pathlib import Path

READY_TIMEOUT = 30.0


def test_local_mode_serves_without_a_control_plane(tmp_path: Path) -> None:
    stub_port = _free_port()
    stub = ThreadingHTTPServer(("127.0.0.1", stub_port), _StubHandler)
    threading.Thread(target=stub.serve_forever, daemon=True).start()

    (tmp_path / "bundle.yml").write_text(
        f"""
keys:
  - sk-inf-local
providers:
  - provider_id: stub
    kind: openai_compatible
    base_url: http://127.0.0.1:{stub_port}
models:
  - model_id: echo
    provider_id: stub
    upstream_model: echo
    input_price_per_mtok: 2.0
    output_price_per_mtok: 5.0
    cache_read_price_per_mtok: 0.25
    cache_write_price_per_mtok: 2.5
    context_window: 128000
    capabilities: [streaming]
""",
        encoding="utf-8",
    )
    (tmp_path / "config.yml").write_text(
        f"""
x-cache-dir: &cache-dir {tmp_path / ".airllm"}
data_plane:
  bundle:
    kind: local
    path: {tmp_path / "bundle.yml"}
  events:
    cache_dir: *cache-dir
""",
        encoding="utf-8",
    )

    port = _free_port()
    log = (tmp_path / "dp.log").open("a", encoding="utf-8")
    process = subprocess.Popen(  # noqa: S603 trusted local console script
        [_bin("airllmdp"), "serve", "--host", "127.0.0.1", "--port", str(port), "--config", str(tmp_path / "config.yml")],
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin", "STUB_API_KEY": "sk-local-upstream", "HOME": str(tmp_path)},
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        assert _poll(lambda: _ready(port), READY_TIMEOUT), (tmp_path / "dp.log").read_text(encoding="utf-8")
        response = httpx.post(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            headers={"authorization": "Bearer sk-inf-local"},
            json={"model": "echo", "messages": [{"role": "user", "content": "hi"}]},
            timeout=10.0,
        )
        assert response.status_code == 200, response.text
        assert response.json()["content"] == [{"type": "text", "text": "ok"}]
        with sqlite3.connect(tmp_path / ".airllm" / "events.db") as connection:
            event = json.loads(connection.execute("SELECT body FROM outbox").fetchone()[0])
        assert event["cache_read_tokens"] == 4
        assert event["cost_input_usd"] == 15 / 1_000_000
        assert event["cost_output_usd"] == 15 / 1_000_000
    finally:
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=10)
        log.close()
        stub.shutdown()
        stub.server_close()


def _ready(port: int) -> bool:
    try:
        return httpx.get(f"http://127.0.0.1:{port}/readyz", timeout=2.0).status_code == 200
    except httpx.HTTPError:
        return False
