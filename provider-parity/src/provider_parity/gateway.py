from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Self, TextIO

import httpx
import yaml

from provider_parity.drivers.base import Connection

if TYPE_CHECKING:
    from types import TracebackType

    from provider_parity.models import Target

OK = 200


def render_bundle(targets: list[Target], api_key: str) -> str:
    if not targets:
        message = "a local gateway bundle needs at least one target"
        raise ValueError(message)
    surfaces = {(target.provider_id, target.surface_id, target.base_url, target.egress_kind) for target in targets}
    if len(surfaces) != 1:
        message = "a local gateway bundle covers exactly one provider surface"
        raise ValueError(message)
    target = targets[0]
    document = {
        "keys": [api_key],
        "providers": [{"provider_id": target.provider_id, "kind": target.egress_kind, "base_url": target.base_url}],
        "models": [
            {
                "model_id": model.model_id,
                "provider_id": model.provider_id,
                "upstream_model": model.upstream_model,
                "input_price_per_mtok": 0.0,
                "output_price_per_mtok": 0.0,
                "cache_read_price_per_mtok": 0.0,
                "cache_write_price_per_mtok": 0.0,
                "context_window": model.context_window,
                "max_output_tokens": model.max_output_tokens,
                "input_modalities": sorted(model.input_modalities),
                "capabilities": sorted(model.capabilities),
                "parameter_support": model.parameter_support,
            }
            for model in targets
        ],
    }
    return yaml.safe_dump(document, sort_keys=False)


def _free_port() -> int:
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return int(connection.getsockname()[1])


class LocalGateway:
    def __init__(self, targets: list[Target], api_key: str = "sk-inf-provider-parity") -> None:
        self.targets = targets
        self.api_key = api_key
        self.port = _free_port()
        self._temporary = TemporaryDirectory(prefix="airllm-parity-")
        self.path = Path(self._temporary.name)
        self.process: subprocess.Popen[str] | None = None
        self.log: TextIO | None = None

    def start(self) -> Self:
        executable = shutil.which("airllmdp")
        if executable is None:
            message = "airllmdp is not on PATH; run `uv sync --all-packages` first"
            raise RuntimeError(message)
        bundle = self.path / "bundle.yml"
        config = self.path / "config.yml"
        bundle.write_text(render_bundle(self.targets, self.api_key), encoding="utf-8")
        config.write_text(
            yaml.safe_dump({"data_plane": {"bundle": {"kind": "local", "path": str(bundle)}, "events": {"kind": "devnull"}}}, sort_keys=False),
            encoding="utf-8",
        )
        self.log = (self.path / "gateway.log").open("a", encoding="utf-8")
        environment = {**os.environ, "GW_CONFIG": str(config)}
        self.process = subprocess.Popen(  # noqa: S603 the harness executes the shipped local data-plane command
            [executable, "serve", "--host", "127.0.0.1", "--port", str(self.port), "--config", str(config)],
            cwd=self.path,
            env=environment,
            stdout=self.log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                break
            try:
                if httpx.get(f"http://127.0.0.1:{self.port}/readyz", timeout=0.5).status_code == OK:
                    return self
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        if self.log is not None:
            self.log.flush()
        detail = (self.path / "gateway.log").read_text(encoding="utf-8")
        message = f"local gateway did not become ready: {detail.strip()[:4000]}"
        raise RuntimeError(message)

    def connection(self, endpoint: str) -> Connection:
        suffix = "/inf" if endpoint == "messages" else "/inf/v1"
        return Connection(base_url=f"http://127.0.0.1:{self.port}{suffix}", api_key=self.api_key, auth="bearer", headers={})

    def close(self) -> None:
        if self.process is not None:
            self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.log is not None:
            self.log.close()
        self._temporary.cleanup()

    def __enter__(self) -> Self:
        try:
            self.start()
        except RuntimeError:
            self.close()
            raise
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None) -> None:
        self.close()
